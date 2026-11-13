"""Offline core regression suite; all hardware I/O is replaced at the driver boundary."""

import json
import math
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

import laser_platform.dmm.backend as dmm
import laser_platform.config as config_module
import laser_platform.devices as devices
import laser_platform.dmm.instrument.visa_client as visa
import laser_platform.instruments as instruments
import laser_platform.opm.backend as opm
import laser_platform.ufc.core as ufc
import laser_platform.ufc.instrument as counter
import laser_platform.wlm.backend as wlm
from laser_platform.config import ConfigStore, default_instrument_settings
from laser_platform.dmm.instrument import InstrumentError
from laser_platform.dmm.models import MeasurementConfig, MeasurementFunction, resolve_dmm_resource
from laser_platform.library import (
    LmpWriter, MAGIC, PAYLOAD_OFFSET, delete_library_item, export_library_series,
    library_frequency_noise, library_item_preview, library_waveform_preview, list_library_files,
    read_metadata, rename_library_item,
    sample_count_from_size, write_metadata,
)
from laser_platform.opm.client import PowerMeterDriverUnavailable, PowerMeterError
from laser_platform.opm.models import PowerMeterConfig
from laser_platform.opm.tlpmx import TlpmxPowerMeterClient
from laser_platform.server import create_server
from laser_platform.stats import RollingStats, estimated_sample_rate
from laser_platform.ufc.allan import default_m_values, frequency_adev, frequency_file_adev, non_overlapping_adev
from laser_platform.wlm.bristol import BristolWavelengthMeterClient
from laser_platform.wlm.client import WavelengthMeterError
from laser_platform.wlm.models import (
    WLM_USB_RESOURCE, WavelengthMeterConfig, WavelengthMeterIdentity,
    canonicalize_wlm_resource, safe_wlm_sample_rate_hz,
)


RESOURCE = "USB0::TEST::INSTR"
KINDS = ("ufc", "dmm", "opm", "wlm")
USB_DMM = "USB0::0x2A8D::0x1301::MY123::INSTR"
USB_DMM_ALIAS = "USB1::10893::4865::MY123::0::INSTR"


@pytest.fixture
def server(tmp_path):
    backend = create_server(config_path=tmp_path / "config.json")
    thread = threading.Thread(target=backend.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield backend
    finally:
        backend.instrument_manager.shutdown()
        backend.shutdown()
        thread.join(timeout=2)
        backend.server_close()
        assert not thread.is_alive()


def request(server, path, payload=None, method=None):
    body = None if payload is None else json.dumps(payload).encode()
    query = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}", data=body,
        headers={"Content-Type": "application/json"}, method=method,
    )
    try:
        response = urllib.request.urlopen(query, timeout=3)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


@pytest.fixture
def usb_sources(monkeypatch):
    manager = Mock(list_resources=Mock(return_value=()))
    monkeypatch.setattr(devices.pyvisa, "ResourceManager", lambda: manager)
    monkeypatch.setattr(devices, "opm_resource_payload", lambda: {"resource_details": [], "error": None})
    monkeypatch.setattr(devices, "bristol_usb_present", lambda: False)
    return manager


@pytest.mark.parametrize("read_error,status", [
    (TimeoutError("identity timed out"), "available"),
    (devices.pyvisa.errors.VisaIOError(devices.pyvisa.constants.StatusCode.error_timeout), "available"),
    (devices.pyvisa.errors.VisaIOError(devices.pyvisa.constants.StatusCode.error_connection_lost), "unavailable"),
])
def test_usb_inventory_merges_aliases_and_keeps_unidentified(server, usb_sources, monkeypatch, read_error, status):
    pm = "USB0::0x1313::0x8075::PM123::0::INSTR"
    unknown = "USB0::1::2::OTHER::INSTR"
    failed = "USB0::1::2::FAILED::INSTR"
    empty = "USB0::1::2::EMPTY::INSTR"
    raw = "USB0::1::2::RAW::RAW"
    usb_sources.list_resources.return_value = (USB_DMM, USB_DMM_ALIAS, pm, unknown, failed, empty, raw, "TCPIP0::host::INSTR")
    answers = {
        devices.resource_key(USB_DMM): "Keysight,34461A,MY123,1.0",
        devices.resource_key(unknown): "Acme,Scope 100,OTHER,2.0",
        devices.resource_key(failed): read_error,
        devices.resource_key(empty): "",
    }
    connections = []

    def opened(resource, **kwargs):
        assert kwargs == {"open_timeout": devices.IDENTITY_TIMEOUT_MS, "access_mode": devices.pyvisa.constants.AccessModes.exclusive_lock}
        response = answers[devices.resource_key(resource)]
        connection = Mock()
        connection.query.side_effect = response if isinstance(response, Exception) else None
        connection.query.return_value = response
        connections.append(connection)
        return connection

    usb_sources.open_resource.side_effect = opened
    monkeypatch.setattr(devices, "opm_resource_payload", lambda: {
        "error": None, "resource_details": [{"resource": "USB1::4883::32885::PM123::INSTR", "manufacturer": "Thorlabs", "model": "PM400", "serial": "PM123", "available": True}],
    })
    before = server.config_store.path.read_bytes()
    http_status, payload = request(server, "/api/devices")
    assert http_status == 200 and not payload["warnings"]
    rows = {item["id"]: item for item in payload["devices"]}
    assert len(rows) == 6
    assert rows[devices.resource_key(USB_DMM)]["type"] == "dmm"
    for vendor in ("Keysight", "Agilent"):
        for model in ("53220A", "53230A"):
            assert devices.identity_fields(f"{vendor},{model},123,1")["type"] == "ufc"
    assert not devices.identity_fields("Vendor,Unknown,123,1")["model"]
    assert rows[devices.resource_key(pm)]["model"] == "PM400" and rows[devices.resource_key(pm)]["type"] == "opm"
    assert rows[devices.resource_key(unknown)]["model"] == "Scope 100" and not rows[devices.resource_key(unknown)]["type"]
    assert rows[devices.resource_key(unknown)]["identification"] == "Identity not recognized by this app."
    assert rows[devices.resource_key(failed)]["status"] == status
    assert str(read_error) in rows[devices.resource_key(failed)]["identification"]
    assert not rows[devices.resource_key(empty)]["model"] and not rows[devices.resource_key(raw)]["model"]
    assert rows[devices.resource_key(empty)]["status"] == "available"
    assert rows[devices.resource_key(raw)]["status"] == "detected"
    assert len(connections) == 4
    for connection in connections:
        connection.query.assert_called_once_with("*IDN?")
        connection.write.assert_not_called()
        connection.close.assert_called_once()
        assert connection.timeout == devices.IDENTITY_TIMEOUT_MS
    usb_sources.list_resources.assert_called_once_with("USB?*")
    usb_sources.close.assert_not_called()
    assert not server.instrument_manager._active_resources
    assert server.config_store.path.read_bytes() == before


def test_usb_discovery_keeps_cached_identity_while_busy_and_clears_disconnected(server, usb_sources):
    manager = server.instrument_manager
    usb_sources.list_resources.return_value = (USB_DMM,)
    connection = Mock(query=Mock(return_value="Keysight,34461A,MY123,1"))
    usb_sources.open_resource.return_value = connection
    manager.devices_payload()
    connection.query.reset_mock()
    key = devices.resource_key(USB_DMM_ALIAS.lower())
    assert key == devices.resource_key(USB_DMM)
    manager._active_resources["acquisition"] = key
    try:
        row = manager.devices_payload()["devices"][0]
        assert row["model"] == "34461A" and row["status"] == "in_use"
        connection.query.assert_not_called()
        manager._device_identities.clear()
        row = manager.devices_payload()["devices"][0]
        assert not row["model"] and "In use" in row["identification"]
    finally:
        manager._active_resources.clear()
    usb_sources.list_resources.return_value = ()
    assert manager.devices_payload()["devices"] == [] and not manager._device_identities


@pytest.mark.parametrize("action", ["device_scan", "counter_discovery", "counter_close"])
def test_visa_borrowers_preserve_active_sessions_until_process_exit(server, monkeypatch, action):
    library = Mock(resource_manager=None)
    library.open_default_resource_manager.return_value = (42, devices.pyvisa.constants.StatusCode.success)
    counter_address = "USB0::0x2A8D::0x1807::COUNTER::INSTR"
    library.list_resources.return_value = (USB_DMM, counter_address)
    monkeypatch.setattr(devices.pyvisa.highlevel, "open_visa_library", lambda path: library)
    monkeypatch.setattr(devices, "opm_resource_payload", lambda: {"resource_details": [], "error": None})
    monkeypatch.setattr(devices, "bristol_usb_present", lambda: False)
    shared = devices.pyvisa.ResourceManager()
    assert devices.pyvisa.ResourceManager() is shared
    active_connection = Mock()
    shared._created_resources.add(active_connection)
    opened = []

    def open_resource(address, **kwargs):
        assert address == counter_address
        connection = Mock(query=Mock(return_value="Keysight,53230A,COUNTER,1"))
        shared._created_resources.add(connection)
        opened.append(connection)
        return connection

    monkeypatch.setattr(shared, "open_resource", open_resource)
    manager = server.instrument_manager
    manager._active_resources["running-dmm"] = devices.resource_key(USB_DMM)
    try:
        if action == "device_scan":
            rows = manager.devices_payload()["devices"]
            assert next(row for row in rows if row["resource"] == USB_DMM)["status"] == "in_use"
        elif action == "counter_discovery":
            assert counter.list_visa_resources() == (USB_DMM, counter_address)
        else:
            client = counter.Keysight53230A()
            client.configure(counter.CounterConfig(counter_address))
            client.connect()
            client.close()
        active_connection.close.assert_not_called()
        assert shared.session == 42
        library.close.assert_not_called()
        for connection in opened:
            connection.close.assert_called_once()
    finally:
        manager._active_resources.pop("running-dmm", None)
        shared._atexit_handler()
    active_connection.close.assert_called_once()
    library.close.assert_called_once_with(42)


@pytest.mark.parametrize("source", ["devices", "resources"])
def test_usb_probe_reservation_blocks_start_and_connection_check(server, usb_sources, source):
    entered, release = threading.Event(), threading.Event()
    manager = server.instrument_manager
    item = manager.add_instrument("dmm")
    usb_sources.list_resources.return_value = (USB_DMM,)

    def identity(command):
        entered.set()
        assert release.wait(3)
        return "Keysight,34461A,MY123,1"

    connection = Mock(query=Mock(side_effect=identity))
    usb_sources.open_resource.return_value = connection
    result = []
    thread = threading.Thread(target=lambda: result.append(
        manager.devices_payload() if source == "devices" else manager.list_resources(item["id"])
    ))
    thread.start()
    try:
        assert entered.wait(2)
        for operation in (manager.start, manager.check_connection):
            with pytest.raises(RuntimeError, match="already using this resource"):
                operation(item["id"], {"resource": USB_DMM_ALIAS})
        assert manager._active_resource_key("dmm", {"resource": USB_DMM_ALIAS}) == devices.resource_key(USB_DMM)
    finally:
        release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert result[0]["devices"][0]["model"] == "34461A" if source == "devices" else result[0]["valid_count"] == 1
    assert not manager._active_resources and not manager._connection_checks
    connection.close.assert_called_once()


@pytest.mark.parametrize("kind,expected", [("ufc", 2), ("dmm", 2), ("opm", 1)])
def test_resource_counts_only_include_recognized_connected_instruments(server, usb_sources, monkeypatch, kind, expected):
    manager = server.instrument_manager
    item = manager.add_instrument(kind)
    counter_resource = "USB0::1::2::COUNTER::INSTR"
    power_resource = "USB0::1::2::POWER::INSTR"
    missing = "USB0::1::2::MISSING::INSTR"
    answers = {
        USB_DMM: "Keysight,34461A,MY123,1.0",
        USB_DMM_ALIAS: "Keysight,34461A,MY123,1.0",
        "TCPIP0::bench.local::INSTR": "Keysight,34465A,LAN,1.0",
        "GPIB0::1::INSTR": "Agilent,34410A,GPIB,1.0",
        counter_resource: "Keysight,53230A,COUNTER,1.0",
        "USB0::1::2::COUNTER20::INSTR": "Agilent,53220A,COUNTER20,1.0",
        power_resource: "Thorlabs,PM400,POWER,1.0",
        "USB0::1::2::OTHER::INSTR": "Acme,Scope 100,OTHER,1.0",
        "USB0::1::2::EMPTY::INSTR": "",
        "USB0::1::2::TIMEOUT::INSTR": TimeoutError("identity timed out"),
        missing: OSError("disconnected"),
    }
    resources = [*answers, "USB0::1::2::RAW::RAW"]
    usb_sources.list_resources.return_value = tuple(resources)
    connections = []

    def opened(resource, **kwargs):
        response = answers[resource]
        if isinstance(response, OSError) and not isinstance(response, TimeoutError):
            raise response
        connection = Mock(query=Mock(return_value=response, side_effect=response if isinstance(response, Exception) else None))
        connections.append(connection)
        return connection

    usb_sources.open_resource.side_effect = opened
    monkeypatch.setattr(instruments, "opm_resource_payload", lambda: {
        "resources": resources, "error": None, "driver_available": True,
        "resource_details": [
            {"resource": power_resource, "manufacturer": "Thorlabs", "model": "PM400", "available": True},
            {"resource": missing, "manufacturer": "Thorlabs", "model": "PM400", "available": False},
            {"resource": USB_DMM, "manufacturer": "Keysight", "model": "34461A", "available": True},
            {"resource": "USB0::1::2::EMPTY::INSTR", "manufacturer": "Thorlabs", "model": "", "available": True},
        ],
    })
    before = server.config_store.path.read_bytes()
    status, payload = request(server, f"/api/instruments/{item['id']}/resources")
    assert status == 200 and payload["valid_count"] == expected
    expected_resources = resources if kind == "opm" else [r for r in resources if r.startswith(("USB", "TCPIP"))]
    assert set(payload["resources"]) == set(expected_resources)
    assert all(not call.args[0].startswith("GPIB") for call in usb_sources.open_resource.call_args_list)
    assert server.config_store.path.read_bytes() == before
    assert not manager._active_resources
    for connection in connections:
        connection.query.assert_called_once_with("*IDN?")
        connection.close.assert_called_once()
        connection.write.assert_not_called()
    usb_sources.close.assert_not_called()
    if kind == "opm":
        usb_sources.open_resource.assert_not_called()


def test_resource_count_preserves_busy_identity_and_handles_missing_drivers(server, usb_sources, monkeypatch):
    manager = server.instrument_manager
    item = manager.add_instrument("dmm")
    address = "TCPIP0::bench.local::INSTR"
    usb_sources.list_resources.return_value = (address,)
    connection = Mock(query=Mock(return_value="Keysight,34461A,LAN,1.0"))
    usb_sources.open_resource.return_value = connection
    assert manager.list_resources(item["id"])["valid_count"] == 1
    manager._active_resources[item["id"]] = devices.resource_key(address)
    usb_sources.open_resource.reset_mock()
    try:
        manager.devices_payload()
        assert manager.list_resources(item["id"])["valid_count"] == 1
        manager._device_identities.clear()
        assert manager.list_resources(item["id"])["valid_count"] == 0
        usb_sources.open_resource.assert_not_called()
    finally:
        manager._active_resources.clear()
    usb_sources.list_resources.side_effect = OSError("VISA unavailable")
    for kind in ("ufc", "dmm"):
        payload = manager.list_resources(manager.add_instrument(kind)["id"])
        assert payload["valid_count"] == 0 and payload["resources"] == [] and payload["error"]
    monkeypatch.setattr(instruments, "opm_resource_payload", lambda: {"resources": [], "error": "TLPMX unavailable"})
    payload = manager.list_resources(manager.add_instrument("opm")["id"])
    assert payload["valid_count"] == 0 and payload["error"]


def test_usb_discovery_partial_failures_and_open_cleanup(server, usb_sources, monkeypatch):
    usb_sources.list_resources.return_value = (USB_DMM,)
    usb_sources.open_resource.side_effect = OSError("connection failed")
    monkeypatch.setattr(devices, "opm_resource_payload", lambda: {"resource_details": [], "error": "TLPMX driver unavailable"})
    monkeypatch.setattr(devices, "bristol_usb_present", Mock(side_effect=TimeoutError()))
    result = server.instrument_manager.devices_payload()
    assert result["warnings"] == ["Bristol USB discovery could not read the local network interfaces."]
    usb_sources.close.assert_not_called()
    assert result["devices"][0]["status"] == "unavailable"
    assert "connection failed" in result["devices"][0]["identification"]
    assert not server.instrument_manager._active_resources
    monkeypatch.setattr(devices.pyvisa, "ResourceManager", Mock(side_effect=OSError("VISA unavailable")))
    result = server.instrument_manager.devices_payload()
    assert result["devices"] == [] and len(result["warnings"]) == 2
    assert not any("Power meter" in warning or "TLPMX" in warning for warning in result["warnings"])


@pytest.mark.parametrize("raw,model,kind", [
    ("Bristol,671A,123,1.0", "671A", "wlm"),
    ("Bristol,771,123,1.0", "771", "wlm"),
    ("Bristol Wavelength Meter @ 10.199.199.1:23", "", ""),
    (TimeoutError("probe timed out"), "", ""),
])
def test_bristol_usb_inventory_requires_present_route_and_real_identity(server, usb_sources, monkeypatch, raw, model, kind):
    probe = Mock()
    probe.side_effect = raw if isinstance(raw, Exception) else None
    probe.return_value = SimpleNamespace(raw=raw)
    monkeypatch.setattr(devices, "_bounded_resource_probe", probe)
    assert server.instrument_manager.devices_payload()["devices"] == []
    probe.assert_not_called()
    monkeypatch.setattr(devices, "bristol_usb_present", lambda: True)
    row = server.instrument_manager.devices_payload()["devices"][0]
    assert row["resource"] == WLM_USB_RESOURCE and row["transport"] == "USB virtual Ethernet"
    assert row["model"] == model and row["type"] == kind
    assert row["status"] == ("unavailable" if isinstance(raw, Exception) else "available")
    assert probe.call_args.args[1].resource == WLM_USB_RESOURCE
    assert not server.instrument_manager._active_resources


@pytest.mark.parametrize("pnp,prefix,next_hop,expected", [
    ("USB\\RNDIS", "10.199.199.0/24", "0.0.0.0", True),
    ("USB\\RNDIS", "10.199.199.1/32", "0.0.0.0", True),
    ("PCI\\ETHERNET", "10.199.199.0/24", "0.0.0.0", False),
    ("USB\\RNDIS", "0.0.0.0/0", "0.0.0.0", False),
    ("USB\\RNDIS", "192.168.1.0/24", "0.0.0.0", False),
    ("USB\\RNDIS", "10.199.199.0/24", "10.199.199.254", False),
    (None, "10.199.199.0/24", "0.0.0.0", False),
])
def test_bristol_usb_route_detection(monkeypatch, pnp, prefix, next_hop, expected):
    monkeypatch.setattr(devices, "sys", SimpleNamespace(platform="win32"))
    run = Mock(return_value=SimpleNamespace(stdout=json.dumps([
        {"pnp_id": pnp, "routes": [{"DestinationPrefix": prefix, "NextHop": next_hop}]},
    ])))
    monkeypatch.setattr(devices.subprocess, "run", run)
    assert devices.bristol_usb_present() is expected
    assert run.call_args.kwargs["timeout"] == 5 and run.call_args.kwargs["check"] is True
    run.return_value.stdout = "[]"
    assert not devices.bristol_usb_present()


def record(directory, kind, values=(1, 1.2, 0.9, 1.1, 1.05, 1.15)):
    unit, value_name, adev_name = {
        "ufc": ("Hz", "frequency_hz", "adev"), "dmm": ("V", "value", "adev"),
        "opm": ("W", "power_w", "adev_w"), "wlm": ("nm", "wavelength_nm", "adev_nm"),
    }[kind]
    writer = LmpWriter(
        directory, kind, kind, "Core check", "Test fixture", RESOURCE, unit,
        sample_layout={
            "kind": "ufc_frequency_f64" if kind == "ufc" else "elapsed_value_f64",
            "record_size": 8 if kind == "ufc" else 16, "dtype": "<f8",
            "value_semantic": value_name, "adev_semantic": adev_name,
            "fields": [{"name": "elapsed_s", "unit": "s"}, {"name": value_name, "unit": unit}],
        },
        settings={"sample_rate_hz": 10, "optical_frequency_hz": 3.5e14,
                  "divide_adev_by_optical_frequency": False, "divide_adev_by_sqrt2": False,
                  "measurement_function": "VOLT:DC", "interval_ms": 100},
    )
    try:
        if kind == "ufc":
            writer.append_ufc_frequency(values)
        else:
            for index, value in enumerate(values):
                writer.append_elapsed_value_sample(index / 10, value)
    finally:
        writer.close()
    return writer.path


def test_configuration_round_trip_and_validation(tmp_path):
    store = ConfigStore(tmp_path / "nested" / "config.json")
    config = store.load()
    assert config["platform"] == {"library_dir": "runs", "color_mode": "auto"}
    assert [item["type"] for item in config["instruments"]] == ["ufc", "dmm"]
    config["instruments"][0]["settings"].update(channel=3, unknown_setting=123)
    config["instruments"].append(dict(config["instruments"][0]))
    config["platform"].update(library_dir=str(tmp_path), unknown_setting=True)
    saved = store.update(config)
    assert store.load() == json.loads(store.path.read_text()) == saved
    assert saved["platform"] == {"library_dir": str(tmp_path), "color_mode": "auto"}
    assert len({item["id"] for item in saved["instruments"]}) == 3
    assert saved["instruments"][0]["settings"]["channel"] == 3
    assert "unknown_setting" not in saved["instruments"][0]["settings"]
    for kind in KINDS:
        settings = default_instrument_settings(kind)
        settings["resource"] = "changed"
        assert default_instrument_settings(kind)["resource"] != "changed"
    with pytest.raises(ValueError, match="unsupported instrument type"):
        store.update({"instruments": [{"type": "unknown"}]})
    assert store.update({"instruments": []})["instruments"] == []


def test_config_store_replaces_json_atomically(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    replacements = []
    original_replace = config_module.os.replace

    def replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr(config_module.os, "replace", replace)
    store.update({"platform": {"color_mode": "dark"}})
    assert replacements and replacements[0][0].parent == tmp_path
    assert replacements[0][1] == store.path
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(store.path.read_text(encoding="utf-8"))["platform"]["color_mode"] == "dark"


def test_color_mode_is_persisted_and_invalid_updates_preserve_settings(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    for mode in ("light", "dark", "auto"):
        store.update({"platform": {"color_mode": mode}})
        assert ConfigStore(store.path).load()["platform"]["color_mode"] == mode
    before = store.path.read_bytes()
    for invalid in ("system", "unknown", None, []):
        with pytest.raises(ValueError, match="color mode"):
            store.update({"platform": {"color_mode": invalid}})
        assert store.path.read_bytes() == before


def test_counter_warning_severity_survives_event_serialization():
    assert ufc.event_from_message(ufc.StatusMessage("Connected: counter"))["data"]["severity"] == "info"
    assert ufc.event_from_message(ufc.StatusMessage("ADEV unavailable", "warning"))["data"]["severity"] == "warning"
    assert ufc.event_from_message(ufc.DoneMessage("Buffer recovery uncertain", None, "warning"))["data"]["severity"] == "warning"


@pytest.mark.parametrize("target,expected", [
    (RESOURCE, RESOURCE),
    (" 192.168.1.50 ", "TCPIP0::192.168.1.50::inst0::INSTR"),
    ("meter.local", "TCPIP0::meter.local::inst0::INSTR"),
    ("TCPIP0::meter.local::5025::SOCKET", "TCPIP0::meter.local::5025::SOCKET"),
])
def test_dmm_resource_is_shared_by_connection_check_and_ownership(server, monkeypatch, target, expected):
    assert resolve_dmm_resource(target) == expected
    manager = server.instrument_manager
    client = Mock(connect=Mock(return_value=SimpleNamespace(raw="Keysight,34461A,123,1")))
    monkeypatch.setattr(instruments, "VisaInstrumentClient", lambda: client)
    item = manager.add_instrument("dmm")
    assert manager.check_connection(item["id"], {"resource": target})["resource"] == expected
    client.connect.assert_called_once_with(expected)
    assert manager._active_resource_key("dmm", {"resource": target}) == devices.resource_key(expected)
    with pytest.raises(ValueError, match="resource"):
        resolve_dmm_resource("   ")


def test_removed_controller_cannot_publish_or_release_new_resource(server):
    manager = server.instrument_manager
    item = manager.add_instrument("dmm")
    old_controller = manager._controllers[item["id"]]
    manager.delete_instrument(item["id"])
    manager._ensure_controller(item)
    manager._active_resources[item["id"]] = "new acquisition"
    subscriber = manager.subscribe()
    try:
        old_controller.publish("done", {})
        assert subscriber.empty()
        assert manager._active_resources[item["id"]] == "new acquisition"
        manager.unsubscribe(subscriber)
        manager.publish("status", {})
        assert subscriber.empty()
    finally:
        manager.unsubscribe(subscriber)
        manager._remove_controller(item["id"])


def test_http_health_config_and_instrument_lifecycle(server, tmp_path):
    assert request(server, "/api/health") == (200, {"ok": True})
    assert request(server, "/missing")[0] == 404
    assert request(server, "/api/instruments", {"type": "unknown"})[0] == 400
    assert request(server, "/api/config", {"platform": {"library_dir": str(tmp_path)}})[0] == 200
    for kind in KINDS:
        status, item = request(server, "/api/instruments", {"type": kind})
        assert status == 200
        path = f"/api/instruments/{item['id']}"
        status, options = request(server, path + "/options")
        assert status == 200 and options["defaults"] == item["settings"]
        assert request(server, path + "/rename", {"display_name": "Bench"})[1]["display_name"] == "Bench"
        assert request(server, path + "/rename", {"display_name": " "})[1]["display_name"] == ""
        status, updated = request(server, path + "/settings", {"unknown_setting": True})
        assert status == 200 and "unknown_setting" not in updated["settings"]
        assert request(server, path, method="DELETE")[0] == 200
    assert len(request(server, "/api/instruments")[1]["instruments"]) == 2
    assert server.config_store.load()["platform"]["library_dir"] == str(tmp_path)


@pytest.mark.parametrize("kind,driver", [
    ("ufc", "Keysight53230A"), ("dmm", "VisaInstrumentClient"),
    ("opm", "TlpmxPowerMeterClient"), ("wlm", "BristolWavelengthMeterClient"),
])
def test_connection_checks_select_driver_and_release_resource(server, monkeypatch, kind, driver):
    identity = "Test,Instrument,123,1.0"
    client = Mock()
    client.connect.return_value = identity if kind == "ufc" else SimpleNamespace(raw=identity)
    monkeypatch.setattr(instruments, driver, lambda: client)
    manager = server.instrument_manager
    item = manager.add_instrument(kind)
    payload = {"resource": RESOURCE} if kind != "wlm" else {"connection_mode": "usb"}
    result = manager.check_connection(item["id"], payload)
    assert result == {"connected": True, "identity": identity, "resource": WLM_USB_RESOURCE if kind == "wlm" else RESOURCE}
    client.close.assert_called_once()
    assert not manager._active_resources and not manager._connection_checks
    assert not manager._controllers[item["id"]].is_running()
    client.connect.side_effect = OSError("disconnected")
    with pytest.raises(OSError, match="disconnected"):
        manager.check_connection(item["id"], payload)
    assert client.close.call_count == 2
    assert not manager._active_resources and not manager._connection_checks


@pytest.mark.parametrize("kind,module,worker_name,done_type", [
    ("ufc", ufc, "AcquisitionWorker", ufc.DoneMessage),
    ("dmm", dmm, "DmmAcquisitionWorker", dmm.DmmDoneMessage),
    ("opm", opm, "OpmAcquisitionWorker", opm.OpmDoneMessage),
    ("wlm", wlm, "WlmAcquisitionWorker", wlm.WlmDoneMessage),
])
def test_acquisition_resource_ownership_and_event_routing(server, monkeypatch, kind, module, worker_name, done_type):
    monkeypatch.setattr(getattr(module, worker_name), "start", lambda self: None)
    manager = server.instrument_manager
    first, second = manager.add_instrument(kind), manager.add_instrument(kind)
    payload = {"resource": RESOURCE} if kind != "wlm" else {
        "connection_mode": "ethernet", "ethernet_resource": "Meter.Local",
    }
    subscriber = manager.subscribe()
    try:
        assert manager.start(first["id"], payload) == {"ok": True}
        with pytest.raises(RuntimeError, match="already running"):
            manager.start(first["id"], payload)
        if kind == "wlm":
            payload = {"connection_mode": "ethernet", "ethernet_resource": "telnet://meter.local:23"}
        with pytest.raises(RuntimeError, match="already using this resource"):
            manager.start(second["id"], payload)
        with pytest.raises(RuntimeError, match="Stop acquisition"):
            manager.delete_instrument(first["id"])
        controller = manager._controllers[first["id"]]
        manager.stop(first["id"])
        controller.messages.put(done_type("finished", None))
        deadline = time.monotonic() + 2
        while True:
            envelope = subscriber.get(timeout=max(0.01, deadline - time.monotonic()))["data"]
            if envelope.get("event") == "done":
                assert envelope["instrument_id"] == first["id"] and envelope["instrument_type"] == kind
                break
        assert first["id"] not in manager._active_resources
        assert manager.start(second["id"], payload) == {"ok": True}
    finally:
        manager.unsubscribe(subscriber)
        for item in (first, second):
            controller = manager._controllers[item["id"]]
            with controller._lock:
                controller._worker = None  # Workers were never started in this control-flow check.


@pytest.mark.parametrize("controller_type,status,done,error", [
    (ufc.BackendController, ufc.StatusMessage("test"), ufc.DoneMessage, ufc.ErrorMessage),
    (dmm.DmmController, dmm.DmmStatusMessage("running", "test"), dmm.DmmDoneMessage, dmm.DmmErrorMessage),
    (opm.OpmController, opm.OpmStatusMessage("running", "test"), opm.OpmDoneMessage, opm.OpmErrorMessage),
    (wlm.WlmController, wlm.WlmStatusMessage("running", "test"), wlm.WlmDoneMessage, wlm.WlmErrorMessage),
])
def test_controller_dispatch_cleanup_before_callback(controller_type, status, done, error, tmp_path):
    subscriber = queue.Queue()

    def on_event(event, data):
        if event in {"done", "error"}:
            assert not controller.is_running() and controller.active_library_file() is None
        subscriber.put({"event": event, "data": data})

    controller = controller_type(on_event)
    try:
        for terminal in (done("done", None), error("failed", "details")):
            controller._worker = SimpleNamespace(library_file=tmp_path / "recording.lmp")
            assert controller.is_running() and controller.active_library_file()
            controller.messages.put(object())
            controller.messages.put(status)
            assert subscriber.get(timeout=2)["data"]["text"] == "test"
            controller.messages.put(terminal)
            controller.messages.put(status)
            assert subscriber.get(timeout=2)["event"] in {"done", "error"}
            assert subscriber.get(timeout=2)["event"] == "status"
            assert not controller.is_running() and controller.active_library_file() is None
    finally:
        controller._worker = None
        controller.shutdown()
        controller._dispatcher.join(timeout=2)
    assert not controller._dispatcher.is_alive()


@pytest.mark.parametrize("kind", KINDS)
def test_empty_current_recording_previews_and_exports(tmp_path, kind):
    path = record(tmp_path, kind, values=())
    preview = library_item_preview(tmp_path, path.name)
    assert preview["metadata"]["sample_count"] == 0
    assert preview["waveform"]["points"] == preview["adev"]["points"] == []
    if kind == "ufc":
        assert preview["metadata"]["ufc_segment_starts"] == [0]
    for series in ("waveform", "adev"):
        output = tmp_path / f"{series}.csv"
        assert export_library_series(tmp_path, path.name, series, output)["row_count"] == 0
        assert len(output.read_text().splitlines()) == 1


@pytest.mark.parametrize("field,value", [
    (("schema_version",), 999),
    (("sample_layout", "dtype"), ">f8"),
    (("sample_layout", "record_size"), 16),
    (("settings", "sample_rate_hz"), None),
    (("settings", "sample_rate_hz"), 0),
    (("settings", "sample_rate_hz"), float("nan")),
    (("settings", "optical_frequency_hz"), None),
    (("settings", "optical_frequency_hz"), -1),
    (("settings", "divide_adev_by_optical_frequency"), None),
    (("settings", "divide_adev_by_sqrt2"), "false"),
    (("ufc_segment_starts",), []),
    (("ufc_segment_starts",), [1]),
    (("ufc_segment_starts",), [False]),
    (("ufc_segment_starts",), [0, 0]),
    (("ufc_segment_starts",), [0, 4, 2]),
    (("ufc_segment_starts",), [0, 7]),
])
def test_recording_readers_reject_missing_or_invalid_measurement_metadata(tmp_path, field, value):
    path = record(tmp_path, "ufc")
    metadata = read_metadata(path)
    target = metadata
    for key in field[:-1]:
        target = target[key]
    if value is None:
        del target[field[-1]]
    else:
        target[field[-1]] = value
    write_metadata(path, metadata)
    with pytest.raises(ValueError, match="LMP"):
        library_item_preview(tmp_path, path.name)
    with pytest.raises(ValueError, match="LMP"):
        library_frequency_noise(tmp_path, path.name)
    for series in ("waveform", "adev"):
        output = tmp_path / f"{series}.csv"
        with pytest.raises(ValueError, match="LMP"):
            export_library_series(tmp_path, path.name, series, output)
        assert not output.exists()


@pytest.mark.parametrize("kind", KINDS)
def test_recording_preview_export_and_data_protection(tmp_path, kind):
    path = record(tmp_path, kind)
    metadata = read_metadata(path)
    original = path.read_bytes()
    assert original.startswith(MAGIC) and len(original) == PAYLOAD_OFFSET + 6 * metadata["sample_layout"]["record_size"]
    assert metadata["sample_count"] == sample_count_from_size(path, metadata) == 6
    assert metadata["ended_at"] and metadata["unit"]
    preview = library_item_preview(tmp_path, path.name)
    assert len(preview["waveform"]["points"]) == 6 and preview["adev"]["points"]
    alias = tmp_path / "alias.csv"
    alias.hardlink_to(path)
    for series in ("waveform", "adev"):
        for destination in (path, alias):
            with pytest.raises(ValueError, match="must not overwrite"):
                export_library_series(tmp_path, path.name, series, destination)
            assert path.read_bytes() == original
        output = tmp_path / f"{series}.csv"
        exported = export_library_series(tmp_path, path.name, series, output)
        assert exported["row_count"] == len(output.read_text().splitlines()) - 1 > 0
        heading = metadata["sample_layout"]["value_semantic" if series == "waveform" else "adev_semantic"]
        assert heading in output.read_text().splitlines()[0].split(",")
    rename_library_item(tmp_path, path.name, "Renamed")
    assert read_metadata(path)["display_name"] == "Renamed"
    outside = tmp_path.parent / f"outside-{kind}.lmp"
    outside.write_bytes(original)
    with pytest.raises(FileNotFoundError):
        library_item_preview(tmp_path, "../" + outside.name)
    assert outside.read_bytes() == original
    with pytest.raises((ValueError, RuntimeError)):
        delete_library_item(tmp_path, path.name, [path])
    assert path.exists()
    (tmp_path / "invalid.lmp").write_bytes(b"invalid")
    assert [item["file"] for item in list_library_files(tmp_path)["items"]] == [path.name]
    delete_library_item(tmp_path, path.name)
    assert not path.exists()


@pytest.mark.parametrize("kind,module,worker_type,driver,event_from_message", [
    ("ufc", ufc, ufc.AcquisitionWorker, "Keysight53230A", ufc.event_from_message),
    ("dmm", dmm, dmm.DmmAcquisitionWorker, "VisaInstrumentClient", dmm.dmm_event_from_message),
    ("opm", opm, opm.OpmAcquisitionWorker, "TlpmxPowerMeterClient", opm.opm_event_from_message),
    ("wlm", wlm, wlm.WlmAcquisitionWorker, "BristolWavelengthMeterClient", wlm.wlm_event_from_message),
])
def test_acquisition_records_samples_and_finishes_adev(tmp_path, monkeypatch, kind, module, worker_type, driver, event_from_message):
    values = np.array([852.0, 852.1, 851.9, 852.2, 852.0, 852.1])
    identity = SimpleNamespace(raw="Test,671B-NIR,123,1", model="671B-NIR")
    client = Mock(connect=Mock(return_value=identity.raw if kind == "ufc" else identity), stop_drain_discarded_samples=0)
    client.stop_and_drain.return_value = iter(())
    monkeypatch.setattr(module, driver, lambda: client)
    messages = queue.Queue()
    payload = {"resource": RESOURCE, "library_dir": str(tmp_path), "interval_ms": 10}
    worker = worker_type(ufc.config_from_payload(payload) if kind == "ufc" else payload, messages)

    def read(*args):
        if kind == "ufc":
            worker.stop()
            return values
        if kind == "dmm":
            batch_index = client.read_batch.call_count - 1
            start = batch_index * 3
            batch = values[start:start + 3]
            if start + len(batch) >= len(values):
                worker.stop()
            return batch
        index = client.read_once.call_count - 1
        if index == len(values) - 1:
            worker.stop()
        return values[index]

    client.read_chunk.side_effect = read
    if kind == "dmm":
        client.read_batch.side_effect = read
        client.points_available.return_value = 0
    else:
        client.read_once.side_effect = read
    worker.start()
    try:
        worker.thread.join(timeout=5)
    finally:
        worker.stop()
        worker.thread.join(timeout=2)
    assert not worker.thread.is_alive() and worker.library_file is None
    client.close.assert_called()
    events = [event_from_message(message) for message in list(messages.queue)]
    assert not any(event["event"] == "error" for event in events), events
    assert any(event["event"] == "adev" and event["data"]["sample_count"] == len(values) for event in events)
    path = next(tmp_path.glob("*.lmp"))
    assert any(event["event"] == "done" and event["data"]["library_file"] == str(path) for event in events)
    preview = library_item_preview(tmp_path, path.name)
    assert preview["metadata"]["sample_count"] == len(values) and preview["metadata"]["ended_at"]
    if kind == "dmm":
        client.connect.assert_called_with(RESOURCE)
        assert preview["metadata"]["settings"]["measurement_function"] == "VOLT:DC"
        assert "connection" not in preview["metadata"]["settings"]
        assert "measurement" not in preview["metadata"]["settings"]
    np.testing.assert_array_equal([point["y"] for point in preview["waveform"]["points"]], values)
    assert preview["adev"]["points"]


def test_library_http_endpoints(server, tmp_path):
    path = record(tmp_path, "ufc")
    request(server, "/api/config", {"platform": {"library_dir": str(tmp_path)}})
    assert request(server, "/api/library")[1]["items"][0]["file"] == path.name
    assert request(server, f"/api/library/item?file={path.name}")[1]["metadata"]["sample_count"] == 6
    assert request(server, "/api/library/export", {"file": path.name, "series": "waveform", "csv_path": str(path)})[0] == 400
    assert request(server, "/api/library/export", {"file": path.name, "series": "waveform", "csv_path": str(tmp_path / "export.csv")})[1]["row_count"] == 6
    assert request(server, "/api/library/rename", {"file": path.name, "display_name": "Saved"})[0] == 200
    assert read_metadata(path)["display_name"] == "Saved"
    assert request(server, "/api/library/delete", {"file": path.name})[0] == 200


def test_dmm_batch_worker_drains_pending_readings_on_stop(tmp_path, monkeypatch):
    identity = SimpleNamespace(raw="Keysight,34461A,123,1", model="34461A")
    client = Mock(connect=Mock(return_value=identity))
    messages = queue.Queue()
    worker = dmm.DmmAcquisitionWorker({"resource": RESOURCE, "library_dir": str(tmp_path)}, messages)
    batches = [np.array([1.0, 2.0]), np.array([3.0, 4.0])]

    def read_batch(_limit):
        values = batches.pop(0) if batches else np.array([3.0, 4.0])
        if len(batches) == 1:
            worker.stop()
        return values

    client.read_batch.side_effect = read_batch
    client.points_available.side_effect = [2, 0]
    monkeypatch.setattr(dmm, "VisaInstrumentClient", lambda: client)
    worker.start()
    worker.thread.join(timeout=5)
    assert not worker.thread.is_alive()
    path = next(tmp_path.glob("*.lmp"))
    preview = library_item_preview(tmp_path, path.name)
    assert [point["y"] for point in preview["waveform"]["points"]] == [1.0, 2.0, 3.0, 4.0]
    assert [point["x"] for point in preview["waveform"]["points"]] == pytest.approx([0.0, 0.24, 0.48, 0.72])
    assert client.read_batch.call_args_list[0].args == (4,)
    assert client.read_batch.call_args_list[1].args == (2,)
    events = [dmm.dmm_event_from_message(message) for message in list(messages.queue)]
    assert not any(event["event"] == "error" for event in events), events
    assert sum(event["event"] == "sample" for event in events) == 4
    assert any(event["event"] == "done" for event in events)
    client.stop.assert_called()


def test_dmm_batch_decode_failure_is_terminal_without_single_read_fallback(tmp_path, monkeypatch):
    identity = SimpleNamespace(raw="Keysight,34461A,123,1", model="34461A")
    client = Mock(connect=Mock(return_value=identity))
    client.read_batch.side_effect = dmm.DmmBatchReadError("malformed batch")
    messages = queue.Queue()
    worker = dmm.DmmAcquisitionWorker({"resource": RESOURCE, "library_dir": str(tmp_path)}, messages)
    monkeypatch.setattr(dmm, "VisaInstrumentClient", lambda: client)
    worker.start()
    worker.thread.join(timeout=5)
    assert not worker.thread.is_alive()
    events = [dmm.dmm_event_from_message(message) for message in list(messages.queue)]
    assert any(event["event"] == "error" and "malformed batch" in event["data"]["text"] for event in events)
    assert not client.read_once.called


def test_dmm_batch_reconnect_reconfigures_and_restarts_sampling():
    client = Mock()
    worker = dmm.DmmAcquisitionWorker({}, queue.Queue())
    measurement = MeasurementConfig()
    assert worker._attempt_reconnect(client, RESOURCE, measurement, 4)
    client.configure.assert_called_once_with(measurement, batch_size=4)
    client.start_sampling.assert_called_once()


def test_waveform_endpoint_is_bounded_and_preserves_recording_span(server, tmp_path):
    values = np.arange(5000, dtype=np.float64)
    path = record(tmp_path, "ufc", values)
    metadata = read_metadata(path)
    metadata["ufc_segment_starts"] = [0, 2500]
    write_metadata(path, metadata)
    request(server, "/api/config", {"platform": {"library_dir": str(tmp_path)}})

    direct = library_waveform_preview(tmp_path, path.name)
    status, result = request(server, f"/api/library/waveform?file={path.name}")
    points = result["waveform"]["points"]
    assert status == 200 and result == direct
    assert result["sample_count"] == len(values)
    assert sum(point["y"] is not None for point in points) <= 1200
    assert points[0]["x"] == 0 and points[-1]["x"] == (len(values) - 1) / 10
    assert any(point["y"] is None for point in points)
    assert request(server, "/api/library/waveform?file=missing.lmp")[0] == 400


def test_frequency_noise_endpoint_reads_recent_recording_and_validates(server, tmp_path):
    path = record(tmp_path, "ufc")
    request(server, "/api/config", {"platform": {"library_dir": str(tmp_path)}})
    endpoint = f"/api/library/frequency-noise?file={path.name}"
    assert request(server, endpoint)[1]["points"] == []
    # A step at a recording boundary must not be interpreted as frequency noise.
    values = np.r_[np.full(70000, 10_000_000.), np.full(2048, 20_000_000.)]
    with path.open("r+b") as handle:
        handle.seek(PAYLOAD_OFFSET)
        handle.write(values.astype("<f8").tobytes())
    metadata = read_metadata(path)
    metadata["ufc_segment_starts"] = [0, 70000]
    from laser_platform.library import write_metadata
    write_metadata(path, metadata)
    status, result = request(server, endpoint)
    assert status == 200
    assert result["sample_count"] == 65536 and result["total_samples"] == len(values)
    assert result["sample_rate_hz"] == 10
    assert result["averages"] > 0 and all(point["y"] == 0 for point in result["points"])
    for parameter in ("segment_length=15", "window=bad", "overlap_percent=99"):
        assert request(server, endpoint + "&" + parameter)[0] == 400
    scalar = record(tmp_path, "dmm")
    assert request(server, f"/api/library/frequency-noise?file={scalar.name}")[0] == 400
    assert request(server, "/api/library/frequency-noise?file=missing.lmp")[0] == 400
    settings = {"fn_segment_length": 4096, "fn_window": "hamming", "fn_overlap_percent": 75,
                "fn_log_x": False, "fn_log_y": True, "analysis_tab": "fn"}
    assert request(server, "/api/instruments/ufc-default/settings", settings)[0] == 200
    saved = request(server, "/api/config")[1]["instruments"][0]["settings"]
    assert all(saved[key] == value for key, value in settings.items())


def test_statistics_and_adev_match_known_values_and_disk(tmp_path):
    stats = RollingStats()
    assert stats.snapshot().count == 0
    for value in (1, 3, 2):
        stats.update(value)
    assert stats.snapshot().to_dict() == {"latest": 2, "minimum": 1, "maximum": 3, "average": 2, "count": 3}
    assert estimated_sample_rate(np.array([0, 0.1, 0.2]), 1) == pytest.approx(10)
    assert estimated_sample_rate(np.array([]), 5) == 5
    assert np.all(non_overlapping_adev(np.ones(16), 10, [1, 2, 4]).adev == 0)
    assert non_overlapping_adev([0, 2, 0, 2], 1, [1]).adev[0] == pytest.approx(math.sqrt(2))
    assert 1000 in default_m_values(5000, 1000)
    values = (np.arange(1024) % 13).astype(float) / 8
    path = tmp_path / "samples.f64"
    values.astype("<f8").tofile(path)
    for optical in (False, True):
        for sqrt2 in (False, True):
            options = dict(sample_rate_hz=10, optical_frequency_hz=2, m_values=[1, 2, 8, 64], divide_by_optical_frequency=optical, divide_by_sqrt2=sqrt2)
            memory = frequency_adev(values, **options)
            disk = frequency_file_adev(path, values.size, max_chunk_samples=17, **options)
            np.testing.assert_allclose(disk.adev, memory.adev, rtol=1e-12, atol=1e-15)
            np.testing.assert_array_equal(disk.pairs, memory.pairs)
            np.testing.assert_array_equal(disk.tau_s, memory.tau_s)
    assert frequency_adev([0, 2, 0, 2], 1, 2, [1]).adev[0] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        frequency_file_adev(path, values.size, 0)


@pytest.mark.parametrize("model,ascii_format,ten_amp", [
    ("34410A", True, False), ("34411A", True, False), ("34460A", False, False),
    ("34461A", False, True), ("34465A", True, True), ("34470A", True, True),
])
def test_dmm_model_commands_and_range_safety(monkeypatch, model, ascii_format, ten_amp):
    resource = Mock()
    resource.query.side_effect = lambda command: {
        "*IDN?": f"Keysight,{model},123,1.0",
        "SYST:ERR?": '+0,"No error"',
        "DATA:POIN?": "+2",
    }[command]
    resource.query_ascii_values.return_value = [1.25, 2.5]
    resource.query_binary_values.return_value = np.array([1.25, 2.5])
    manager = Mock(open_resource=Mock(return_value=resource))
    monkeypatch.setattr(visa.pyvisa, "ResourceManager", lambda: manager)
    client = visa.VisaInstrumentClient()
    try:
        assert client.connect(RESOURCE).model == model
        client.configure(MeasurementConfig(), batch_size=4)
        writes = [call.args[0] for call in resource.write.call_args_list]
        assert "CONF:VOLT:DC AUTO" in writes and "VOLT:DC:NPLC 1.0" in writes
        assert "TRIG:SOUR IMM" in writes and "TRIG:COUN INF" in writes
        assert "SAMP:COUN 4" in writes and "SAMP:SOUR TIM" in writes and "SAMP:TIM 0.24" in writes
        assert ("FORM:DATA ASC" in writes) == ascii_format
        if not ascii_format:
            assert "FORM:DATA REAL,64" in writes
        assert resource.timeout == 5000 and resource.read_termination == "\n"
        for function in (MeasurementFunction.CURR_DC, MeasurementFunction.CURR_AC):
            resource.write.reset_mock()
            config = MeasurementConfig(function=function, autorange=False, range_value=10)
            if ten_amp:
                client.configure(config, batch_size=4)
                resource.write.assert_any_call(f"{function.value}:TERM 10")
            else:
                with pytest.raises((InstrumentError, ValueError)):
                    client.configure(config, batch_size=4)
                resource.write.assert_not_called()
        resource.write.reset_mock()
        client.configure(MeasurementConfig(function=MeasurementFunction.CURR_DC, autorange=False, range_value=3), batch_size=4)
        assert all(":TERM 10" not in call.args[0] for call in resource.write.call_args_list)
        client.start_sampling()
        assert np.array_equal(client.read_batch(4), np.array([1.25, 2.5]))
        assert client.points_available() == 2
        resource.write.assert_any_call("INIT")
        client.stop()
        resource.write.assert_any_call("ABOR")
    finally:
        client.close()
    assert client.identity is None and client.resource_name is None
    resource.close.assert_called_once()


def test_dmm_discovery_and_error_cleanup(monkeypatch):
    resource = Mock()
    manager = Mock(open_resource=Mock(return_value=resource), list_resources=Mock(return_value=(RESOURCE, "TCPIP0::host::INSTR", "GPIB0::1::INSTR", "ASRL1::INSTR")))
    monkeypatch.setattr(visa.pyvisa, "ResourceManager", lambda: manager)
    client = visa.VisaInstrumentClient()
    assert client.discover_resources() == ["TCPIP0::host::INSTR", RESOURCE]
    for identity in ("HP,34401A,123,1", OSError("IDN failed")):
        resource.query.side_effect = identity if isinstance(identity, Exception) else None
        resource.query.return_value = identity
        with pytest.raises(InstrumentError):
            client.connect(RESOURCE)
        assert client.identity is None
    assert resource.close.call_count == 2
    resource.query.side_effect = None
    resource.query.return_value = "Keysight,34461A,123,1"
    client.connect(RESOURCE)
    try:
        resource.query.return_value = '-200,"Execution error"'
        with pytest.raises(InstrumentError, match="Execution error"):
            client.configure(MeasurementConfig(), batch_size=4)
        resource.query_binary_values.side_effect = OSError("read failed")
        with pytest.raises(InstrumentError, match="read failed"):
            client.read_batch(4)
    finally:
        client.close()


@pytest.mark.parametrize("model", ["53220A", "53230A"])
def test_counter_scpi_binary_read_and_fixed_configuration(monkeypatch, model):
    resource = Mock(query=Mock(return_value=f"Keysight,{model},123,1"), query_binary_values=Mock(return_value=[10.0, 11.0]))
    manager = Mock(open_resource=Mock(return_value=resource))
    monkeypatch.setattr(counter.pyvisa, "ResourceManager", lambda: manager)
    client = counter.Keysight53230A()
    try:
        for channel, frequency in ((1, 1e7), (2, 1e7), (3, 1e8)):
            config = counter.CounterConfig(RESOURCE, channel=channel, sample_rate_hz=100)
            client.configure(config)
            if channel == 1:
                assert model in client.connect()
                client.configure(config)
            assert config.expected_frequency_hz == frequency and config.chunk_size == 100
            resource.write.assert_any_call(f"CONF:FREQ {frequency},DEF,(@{channel})")
        resource.write.assert_any_call("FORM:DATA REAL,64")
        resource.write.assert_any_call("SENS:FREQ:GATE:TIME 0.01")
        client.start()
        np.testing.assert_array_equal(client.read_chunk(2), [10, 11])
        assert resource.query_binary_values.call_args.kwargs["datatype"] == "d"
        assert resource.query_binary_values.call_args.kwargs["is_big_endian"] is True
        client.abort()
        resource.write.assert_any_call("ABOR")
    finally:
        client.close()
    resource.close.assert_called_once()
    manager.close.assert_not_called()
    for rate in (1, 10, 100, 1000, 5000, 10000, 50000):
        assert ufc.config_from_payload({"resource": RESOURCE, "sample_rate_hz": rate}).sample_rate_hz == rate
    for payload in ({"resource": ""}, {"resource": RESOURCE, "channel": 4}, {"resource": RESOURCE, "sample_rate_hz": 5}):
        with pytest.raises(ValueError):
            ufc.config_from_payload(payload)


@pytest.mark.parametrize("rate", [100000, 500000])
def test_removed_counter_rates_reject_acquisition(rate):
    with pytest.raises(ValueError, match="sample_rate_hz"):
        ufc.config_from_payload({"resource": RESOURCE, "sample_rate_hz": rate})


@pytest.mark.parametrize("buffer_size", [0, 10_017])
@pytest.mark.parametrize("rate", [1000, 50000])
def test_counter_stop_drains_exact_buffer_and_partial_batch(monkeypatch, buffer_size, rate):
    pending = list(range(buffer_size))
    commands = []
    resource = Mock(timeout=1234)
    client = counter.Keysight53230A()
    client.configure(counter.CounterConfig(RESOURCE, sample_rate_hz=rate))
    client._inst = resource

    def query(command):
        commands.append(command)
        if command == "*OPC?":
            return "1\n"
        assert command == "DATA:POIN?"
        return f"+{len(pending)}\n"

    def read(command, **kwargs):
        commands.append(command)
        count = int(command.split()[1])
        assert 0 < count <= len(pending)
        assert kwargs["datatype"] == "d" and kwargs["is_big_endian"]
        values = pending[:count]
        del pending[:count]
        return np.array(values, dtype=float)

    resource.write.side_effect = commands.append
    resource.query.side_effect = query
    resource.query_binary_values.side_effect = read
    batches = list(client.stop_and_drain())
    assert commands[:4] == ["DATA:POIN?", "ABOR", "*OPC?", "DATA:POIN?"]
    assert commands[-1] == "DATA:POIN?"
    assert resource.timeout == 1234
    assert pending == []
    if buffer_size:
        assert [len(batch) for batch in batches] == [10_000, 17]
        np.testing.assert_array_equal(np.concatenate(batches), np.arange(buffer_size))
    else:
        assert batches == []
        resource.query_binary_values.assert_not_called()


@pytest.mark.parametrize("snapshot_count", [0, 1, 3])
def test_counter_stop_preserves_pre_abort_readings_and_excludes_abort_tail(monkeypatch, snapshot_count):
    monkeypatch.setattr(counter, "STOP_DRAIN_BATCH_SIZE", 2)
    resource = Mock(timeout=1234)
    resource.query.side_effect = [str(snapshot_count), "1", "5", "3", "1", "0"]
    resource.query_binary_values.side_effect = [np.array([400e6, 400e6+1]), np.array([40.98, 400e6+2]), np.array([2.9])]
    client = counter.Keysight53230A()
    client.configure(counter.CounterConfig(RESOURCE, sample_rate_hz=50000))
    client._inst = resource
    batches = list(client.stop_and_drain())
    np.testing.assert_array_equal(np.concatenate(batches) if batches else [], [400e6, 400e6+1, 40.98][:snapshot_count])
    assert resource.query_binary_values.call_count == 3
    assert client.stop_drain_discarded_samples == 5 - snapshot_count
    assert resource.timeout == 1234


@pytest.mark.parametrize("failure", ["abort", "confirmation", "snapshot", "count", "read", "empty", "changed", "lost"])
def test_counter_drain_failures_propagate_and_restore_timeout(failure):
    resource = Mock(timeout=1234)
    resource.query.side_effect = ["2", "1", "2", "0"]
    resource.query_binary_values.return_value = np.array([1., 2.])
    if failure == "abort":
        resource.write.side_effect = OSError("disconnected")
    elif failure == "confirmation":
        resource.query.side_effect = ["2", "0"]
    elif failure == "snapshot":
        resource.query.side_effect = ["-1"]
    elif failure == "count":
        resource.query.side_effect = ["2", "1", "-1"]
    elif failure == "read":
        resource.query_binary_values.side_effect = TimeoutError("transfer timed out")
    elif failure == "empty":
        resource.query_binary_values.return_value = np.array([])
    elif failure == "changed":
        resource.query.side_effect = ["2", "1", "2", "2"]
    elif failure == "lost":
        resource.query.side_effect = ["2", "1", "1"]
    client = counter.Keysight53230A()
    client.configure(counter.CounterConfig(RESOURCE))
    client._inst = resource
    with pytest.raises((OSError, RuntimeError)):
        list(client.stop_and_drain())
    assert resource.timeout == 1234
    if failure == "abort":
        resource.query.assert_called_once_with("DATA:POIN?")
    if failure == "snapshot":
        resource.write.assert_not_called()


def test_counter_drain_deadline_preserves_yielded_batch(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(counter.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(counter, "STOP_DRAIN_TIMEOUT_S", 1.0)
    resource = Mock(timeout=10_000)
    resource.query.side_effect = ["2", "1", "2"]
    resource.query_binary_values.return_value = np.array([1., 2.])
    client = counter.Keysight53230A()
    client.configure(counter.CounterConfig(RESOURCE))
    client._inst = resource
    batches = client.stop_and_drain()
    np.testing.assert_array_equal(next(batches), [1., 2.])
    assert resource.timeout == 1000
    clock[0] = 1.01
    with pytest.raises(TimeoutError, match="Timed out"):
        next(batches)
    assert resource.timeout == 10_000
    assert resource.query.call_count == 3


@pytest.mark.parametrize("failure", [None, "drain", "inflight"])
def test_counter_stop_serializes_io_and_finalizes_all_saved_readings(tmp_path, monkeypatch, failure):
    in_read, finish_read = threading.Event(), threading.Event()
    command_threads = []
    values = np.arange(10., 16.)
    tail = np.arange(16., 21.)
    client = Mock(connect=Mock(return_value="Keysight,53230A,TEST,1"), stop_drain_discarded_samples=2)
    messages = queue.Queue()
    worker = ufc.AcquisitionWorker(ufc.config_from_payload({
        "resource": RESOURCE, "library_dir": str(tmp_path),
    }), messages)

    def read(_count):
        command_threads.append(threading.get_ident())
        in_read.set()
        assert finish_read.wait(3)
        if failure == "inflight":
            raise OSError("partial binary reply")
        return values

    def drain():
        command_threads.append(threading.get_ident())
        yield tail[:3]
        if failure == "drain":
            raise TimeoutError("buffer transfer timed out")
        yield tail[3:]

    client.read_chunk.side_effect = read
    client.stop_and_drain.side_effect = drain
    client.abort.side_effect = lambda: command_threads.append(threading.get_ident())
    monkeypatch.setattr(ufc, "Keysight53230A", lambda: client)
    worker.start()
    try:
        assert in_read.wait(3)
        worker.stop()
        worker.stop()  # repeated requests must not send commands or duplicate data
        client.abort.assert_not_called()
        client.stop_and_drain.assert_not_called()
    finally:
        finish_read.set()
        worker.stop()
        worker.thread.join(timeout=5)
    assert not worker.thread.is_alive()
    assert set(command_threads) == {worker.thread.ident}
    client.close.assert_called_once()
    path = next(tmp_path.glob("*.lmp"))
    metadata = read_metadata(path)
    expected = [] if failure == "inflight" else np.concatenate((values, tail[:3] if failure else tail))
    np.testing.assert_array_equal(np.fromfile(path, dtype="<f8", offset=PAYLOAD_OFFSET), expected)
    assert metadata["sample_count"] == len(expected) and metadata["ended_at"]
    assert metadata["stop_drain"]["complete"] is (failure is None)
    assert metadata["stop_drain"]["saved_samples"] == (0 if failure == "inflight" else 3 if failure else 5)
    assert metadata["stop_drain"]["discarded_after_stop"] == (0 if failure == "inflight" else 2)
    events = [ufc.event_from_message(message) for message in list(messages.queue)]
    assert not any(event["event"] == "error" for event in events)
    done = next(event for event in events if event["event"] == "done")
    assert done["data"]["library_file"] == str(path)
    assert (done["data"]["text"] == "Stopped cleanly") is (failure is None)
    if failure == "inflight":
        client.stop_and_drain.assert_not_called()
        assert "partial binary reply" in metadata["stop_drain"]["error"]
    else:
        client.stop_and_drain.assert_called_once()
        data = [event["data"] for event in events if event["event"] == "data"]
        assert data[-1]["total_samples"] == len(expected)
        adev = [event["data"] for event in events if event["event"] == "adev"]
        assert adev[-1]["sample_count"] == len(expected)


def test_counter_stop_before_start_does_not_connect_or_read(tmp_path, monkeypatch):
    client = Mock()
    monkeypatch.setattr(ufc, "Keysight53230A", lambda: client)
    messages = queue.Queue()
    worker = ufc.AcquisitionWorker(ufc.config_from_payload({
        "resource": RESOURCE, "library_dir": str(tmp_path),
    }), messages)
    worker.stop()
    worker.start()
    worker.thread.join(timeout=2)
    assert not worker.thread.is_alive()
    client.connect.assert_not_called()
    client.start.assert_not_called()
    client.stop_and_drain.assert_not_called()
    assert not list(tmp_path.glob("*.lmp"))
    assert any(isinstance(message, ufc.DoneMessage) for message in list(messages.queue))


def test_counter_shutdown_waits_for_buffer_and_file_finalization(tmp_path, monkeypatch):
    in_read, finish_read, in_drain, finish_drain = (threading.Event() for _ in range(4))
    client = Mock(connect=Mock(return_value="Keysight,53230A,TEST,1"), stop_drain_discarded_samples=0)

    def read(_count):
        in_read.set()
        assert finish_read.wait(3)
        return np.arange(4.)

    def drain():
        in_drain.set()
        assert finish_drain.wait(3)
        yield np.arange(4., 7.)

    client.read_chunk.side_effect = read
    client.stop_and_drain.side_effect = drain
    monkeypatch.setattr(ufc, "Keysight53230A", lambda: client)
    controller = ufc.BackendController(lambda event, data: None)
    controller.start_acquisition({"resource": RESOURCE, "library_dir": str(tmp_path)})
    worker = controller._worker
    shutdown_thread = threading.Thread(target=controller.shutdown)
    try:
        assert in_read.wait(3)
        shutdown_thread.start()
        assert worker.stop_event.wait(1)
        finish_read.set()
        assert in_drain.wait(2)
        assert shutdown_thread.is_alive()
        assert not worker.recording_finalized.is_set()
        finish_drain.set()
        shutdown_thread.join(timeout=3)
        assert not shutdown_thread.is_alive()
        path = next(tmp_path.glob("*.lmp"))
        metadata = read_metadata(path)
        assert metadata["ended_at"] and metadata["sample_count"] == 7
        assert metadata["stop_drain"]["complete"]
        np.testing.assert_array_equal(np.fromfile(path, dtype="<f8", offset=PAYLOAD_OFFSET), np.arange(7.))
    finally:
        finish_read.set()
        finish_drain.set()
        worker.stop()
        worker.thread.join(timeout=5)
        if shutdown_thread.ident is not None:
            shutdown_thread.join(timeout=5)
        controller.shutdown()
    assert not worker.thread.is_alive()


def tlpmx_dll(flags=0x21):
    names = "findRsrc getRsrcName getRsrcInfo init identificationQuery getSensorInfo setTimeoutValue setPowerUnit setWavelength setPowerAutoRange getPowerRange setPowerRange measPower close errorMessage".split()
    dll = SimpleNamespace(**{f"TLPMX_{name}": Mock(return_value=0) for name in names})

    def pointer(target, value):
        target._obj.value = value
        return 0

    def buffers(targets, values):
        for target, value in zip(targets, values):
            target.value = value
        return 0

    def resource_info(_session, _index, model, serial, manufacturer, available):
        buffers((model, serial, manufacturer), (b"PM100D", b"123", b"Thorlabs"))
        return pointer(available, 1)

    dll.TLPMX_findRsrc.side_effect = lambda session, count: pointer(count, 1)
    dll.TLPMX_getRsrcName.side_effect = lambda session, index, name: buffers((name,), (RESOURCE.encode(),))
    dll.TLPMX_getRsrcInfo.side_effect = resource_info
    dll.TLPMX_init.side_effect = lambda resource, query, reset, session: pointer(session, 7)
    dll.TLPMX_identificationQuery.side_effect = lambda session, *outputs: buffers(outputs, (b"Thorlabs", b"PM100D", b"123", b"1.0"))
    dll.TLPMX_getSensorInfo.side_effect = lambda *args: pointer(args[6], flags)
    dll.TLPMX_getPowerRange.side_effect = lambda session, selector, output, channel: pointer(output, 1e-6 if selector.value == 1 else 1.0)
    dll.TLPMX_measPower.side_effect = lambda session, output, channel: pointer(output, 0.00125)
    dll.TLPMX_errorMessage.side_effect = lambda session, status, output: buffers((output,), (b"driver error",))
    return dll


@pytest.mark.parametrize("flags", [0x21, 0x01])
def test_power_meter_driver_contract_and_range_validation(flags):
    dll = tlpmx_dll(flags)
    client = TlpmxPowerMeterClient(dll=dll)
    config = PowerMeterConfig(resource=RESOURCE)
    assert client.discover_resources()[0].resource == RESOURCE
    dll.TLPMX_close.assert_called_once()
    try:
        assert client.connect(config).model == "PM100D"
        client.configure(config)
        assert dll.TLPMX_setWavelength.called == bool(flags & 0x20)
        assert dll.TLPMX_setPowerUnit.call_args.args[1].value == 0
        assert dll.TLPMX_setPowerUnit.call_args.args[2].value == 1
        assert dll.TLPMX_setTimeoutValue.call_args.args[1].value == 5000
        assert client.read_once() == pytest.approx(0.00125)
        dll.TLPMX_setPowerAutoRange.reset_mock()
        with pytest.raises(ValueError, match="outside"):
            client.configure(replace(config, autorange=False, manual_range_w=2))
        dll.TLPMX_setPowerAutoRange.assert_not_called()
        client.configure(replace(config, autorange=False, manual_range_w=0.01))
        assert dll.TLPMX_setPowerAutoRange.call_args.args[1].value == 0
        assert dll.TLPMX_setPowerRange.call_args.args[1].value == 0.01
        dll.TLPMX_measPower.side_effect = None
        dll.TLPMX_measPower.return_value = -7
        with pytest.raises(PowerMeterError, match="driver error"):
            client.read_once()
    finally:
        client.close()
    assert client.identity is None and client.sensor is None and client.resource_name is None


def test_power_meter_missing_driver_and_partial_connection_cleanup(caplog):
    loader = Mock(side_effect=OSError("not found"))
    def missing_client():
        return TlpmxPowerMeterClient(dll_loader=loader, candidate_paths=["one.dll", "two.dll"])
    with pytest.raises(PowerMeterDriverUnavailable) as error:
        missing_client().discover_resources()
    assert str(error.value) == "TLPMX driver unavailable. Install Thorlabs Optical Power Monitor."
    assert "one.dll" in error.value.details and "two.dll" in caplog.text
    payload = opm.opm_resource_payload(client_factory=missing_client)
    assert payload["resources"] == [] and not payload["driver_available"]
    assert payload["error_code"] == "tlpmx_driver_unavailable" and ".dll" not in payload["error"]
    dll = tlpmx_dll(flags=0)
    client = TlpmxPowerMeterClient(dll=dll)
    with pytest.raises(PowerMeterError, match="not a power-capable"):
        client.connect(PowerMeterConfig(resource=RESOURCE))
    assert client.identity is None and client.sensor is None
    dll.TLPMX_close.assert_called_once()
    with pytest.raises(ValueError, match="channel 1"):
        PowerMeterConfig.from_payload({"resource": RESOURCE, "channel": 2})


def test_wavelength_endpoints_and_safe_rates():
    assert WavelengthMeterConfig.from_payload({}).resource == WLM_USB_RESOURCE
    for endpoint in ("Meter.Local", "meter.local:23", "TELNET://METER.LOCAL:23"):
        assert canonicalize_wlm_resource(endpoint) == "meter.local:23"
    assert canonicalize_wlm_resource("telnet://[2001:DB8::1]:2323") == "[2001:db8::1]:2323"
    for endpoint in ("", "host:0", "host:65536", "host:abc", "http://host", "telnet://user@host", "telnet://host/path"):
        with pytest.raises(ValueError):
            canonicalize_wlm_resource(endpoint)
    for model, wavelength, expected in (("671A", None, 2.5), ("671A", 852, 4), ("671B-NIR", None, 10), ("671B-IR", 852, 2.5)):
        identity = WavelengthMeterIdentity("Bristol", model, "123", "1.0", model)
        assert safe_wlm_sample_rate_hz(identity, wavelength) == expected


@pytest.mark.parametrize("model,command", [("671A", ":READ:WAV?"), ("771", ":READ:SCAL:WAV?")])
def test_wavelength_telnet_queries_and_invalid_readings(model, command):
    connection = Mock()
    connection.read_some.side_effect = [b"Welcome\r\n", TimeoutError()]
    connection.readline.side_effect = [f"Bristol,{model},123,1.0\r\n", "1\r\n", b"852.125\r\n"]
    factory = Mock(return_value=connection)
    client = BristolWavelengthMeterClient(factory)
    try:
        assert client.connect(WavelengthMeterConfig()).model == model
        factory.assert_called_once_with("10.199.199.1", 23, 5.0)
        assert client.read_once() == 852.125
        connection.write.assert_any_call(command + "\r\n")
        for reading in ("bad", "nan", "inf", "0", "-2", TimeoutError(), EOFError()):
            connection.readline.side_effect = reading if isinstance(reading, Exception) else None
            connection.readline.return_value = reading
            with pytest.raises(WavelengthMeterError):
                client.read_once()
    finally:
        client.close()
    connection.close.assert_called_once()


def test_wavelength_probe_timeout_and_shutdown_finalize_recording(tmp_path, monkeypatch):
    released = threading.Event()
    reading = threading.Event()
    identity = WavelengthMeterIdentity("Bristol", "671A", "123", "1", "Bristol,671A,123,1")
    def blocked(*args):
        reading.set()
        assert released.wait(2), "read did not unblock"
        raise OSError("closed")
    client = Mock(connect=Mock(return_value=identity), read_once=Mock(side_effect=blocked), close=Mock(side_effect=released.set))
    worker = wlm.WlmAcquisitionWorker({"library_dir": str(tmp_path)}, queue.Queue(), client_factory=lambda: client)
    worker.start()
    try:
        assert reading.wait(2)
    finally:
        worker.stop()
        worker.thread.join(timeout=3)
    assert not worker.thread.is_alive()
    messages = list(worker.out_queue.queue)
    assert not any(isinstance(item, wlm.WlmErrorMessage) for item in messages)
    done = next(item for item in messages if isinstance(item, wlm.WlmDoneMessage))
    assert read_metadata(done.library_file)["ended_at"]
    released.clear()
    client.connect.side_effect = blocked
    monkeypatch.setattr(wlm, "WLM_OPERATION_TIMEOUT_S", 0.03)
    started = time.monotonic()
    payload = wlm.wlm_resource_payload({}, client_factory=lambda: client)
    assert time.monotonic() - started < 1
    assert payload["resources"] == [WLM_USB_RESOURCE]
    assert not payload["resource_details"][0]["available"] and "timed out" in payload["error"]
    assert released.is_set()
