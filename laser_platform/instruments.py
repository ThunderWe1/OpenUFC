from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyvisa

from laser_platform.config import ConfigStore, default_instrument_settings, merge_dicts
from laser_platform.devices import IDENTITY_FIELDS, _visa_identity, identity_fields, resource_key, scan_usb_devices
from laser_platform.dmm.backend import DmmController, dmm_options
from laser_platform.dmm.instrument import VisaInstrumentClient
from laser_platform.dmm.models import resolve_dmm_resource
from laser_platform.opm.backend import OpmController, opm_options, opm_resource_payload
from laser_platform.opm.models import PowerMeterConfig
from laser_platform.opm.tlpmx import TlpmxPowerMeterClient
from laser_platform.ufc.core import BackendController
from laser_platform.ufc.instrument import (
    CounterConfig,
    Keysight53230A,
    list_visa_resources,
)
from laser_platform.wlm.backend import (
    WlmController,
    _bounded_resource_probe,
    wlm_options,
    wlm_resource_payload,
)
from laser_platform.wlm.bristol import BristolWavelengthMeterClient
from laser_platform.wlm.models import (
    WavelengthMeterConfig,
    canonicalize_wlm_resource,
)


INSTRUMENT_TYPES: dict[str, dict[str, str]] = {
    "ufc": {"type": "ufc", "label": "Universal Frequency Counter"},
    "dmm": {"type": "dmm", "label": "Digital Multimeter"},
    "opm": {"type": "opm", "label": "Optical Power Meter"},
    "wlm": {"type": "wlm", "label": "Wavelength Meter"},
}


def _new_instance_id(kind: str) -> str:
    return f"{kind}-{uuid4().hex[:8]}"


class InstrumentManager:
    def __init__(self, config_store: ConfigStore) -> None:
        self.config_store = config_store
        self._controllers: dict[str, BackendController | DmmController | OpmController | WlmController] = {}
        self._active_resources: dict[str, str] = {}
        self._connection_checks: set[str] = set()
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._device_scan_lock = threading.Lock()
        self._device_identities: dict[str, dict[str, str]] = {}
        self._ensure_configured_controllers()

    def devices_payload(self) -> dict[str, Any]:
        with self._device_scan_lock:
            result = scan_usb_devices(self._identify_device)
            present = {device["id"] for device in result["devices"]}
            with self._lock:
                present.update(self._active_resources.values())
            self._device_identities = {key: value for key, value in self._device_identities.items() if key in present}
            return result

    def _identify_device(self, device: dict[str, Any], query) -> None:
        key = device["id"]
        owner = f"device-probe-{uuid4().hex}"
        with self._lock:
            if key in self._active_resources.values() or device["status"] == "in_use":
                for field, value in self._device_identities.get(key, {}).items():
                    if not device[field]:
                        device[field] = value
                device.update(status="in_use", identification="In use; identity query skipped.")
                return
            self._active_resources[owner] = key
        try:
            if query is not None:
                device.update(query())
                device["status"] = "available"
            if device["model"]:
                device.update(status="available", identification=("Identified" if device["type"]
                              else "Identity not recognized by this app."))
                self._device_identities[key] = {field: device[field] for field in IDENTITY_FIELDS}
            elif not device["identification"]:
                device["identification"] = ("No usable model identity returned." if query is not None
                                            else "This interface does not expose a standard identity query.")
        except Exception as exc:
            device.update(status="unavailable", identification=f"Identity query failed: {exc}")
        finally:
            with self._lock:
                self._active_resources.pop(owner, None)

    def instruments_payload(self) -> dict[str, Any]:
        self._ensure_configured_controllers()
        instruments = []
        for item in self._load_instruments():
            controller = self._ensure_controller(item)
            instruments.append(
                {
                    "id": item["id"],
                    "type": item["type"],
                    "display_name": item.get("display_name", ""),
                    "settings": item.get("settings", {}),
                    "running": controller.is_running(),
                }
            )
        return {"types": list(INSTRUMENT_TYPES.values()), "instruments": instruments}

    def add_instrument(self, kind: str) -> dict[str, Any]:
        kind = str(kind or "").lower()
        if kind not in INSTRUMENT_TYPES:
            raise ValueError("instrument type must be 'ufc', 'dmm', 'opm', or 'wlm'")
        config = self.config_store.load()
        instruments = list(config.get("instruments", []))
        item = {
            "id": _new_instance_id(kind),
            "type": kind,
            "settings": default_instrument_settings(kind),
        }
        instruments.append(item)
        updated = self.config_store.update({"instruments": instruments})
        normalized = self._find_instrument(updated["instruments"], item["id"])
        self._ensure_controller(normalized)
        return self._public_instrument(normalized)

    def delete_instrument(self, instance_id: str) -> dict[str, Any]:
        item = self._instrument_or_raise(instance_id)
        controller = self._ensure_controller(item)
        if controller.is_running():
            raise RuntimeError("Stop acquisition before deleting this instrument")
        config = self.config_store.load()
        instruments = [entry for entry in config.get("instruments", []) if entry.get("id") != instance_id]
        updated = self.config_store.update({"instruments": instruments})
        self._remove_controller(instance_id)
        return {"ok": True, "instruments": updated.get("instruments", [])}

    def rename_instrument(self, instance_id: str, display_name: str) -> dict[str, Any]:
        config = self.config_store.load()
        instruments = []
        updated_item: dict[str, Any] | None = None
        next_name = str(display_name or "").strip()
        for item in config.get("instruments", []):
            if item.get("id") == instance_id:
                item = dict(item)
                if next_name:
                    item["display_name"] = next_name
                else:
                    item.pop("display_name", None)
                updated_item = item
            instruments.append(item)
        if updated_item is None:
            raise KeyError(f"unknown instrument: {instance_id}")
        updated = self.config_store.update({"instruments": instruments})
        return self._public_instrument(self._find_instrument(updated["instruments"], instance_id))

    def update_settings(self, instance_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        config = self.config_store.load()
        instruments = []
        updated_item: dict[str, Any] | None = None
        for item in config.get("instruments", []):
            if item.get("id") == instance_id:
                merged = merge_dicts(item.get("settings", {}), settings)
                item = {**item, "settings": merged}
                updated_item = item
            instruments.append(item)
        if updated_item is None:
            raise KeyError(f"unknown instrument: {instance_id}")
        updated = self.config_store.update({"instruments": instruments})
        return self._find_instrument(updated["instruments"], instance_id)

    def options(self, instance_id: str) -> dict[str, Any]:
        item = self._instrument_or_raise(instance_id)
        if item["type"] == "dmm":
            return dmm_options(item.get("settings", {}))
        if item["type"] == "opm":
            return opm_options(item.get("settings", {}))
        if item["type"] == "wlm":
            return wlm_options(item.get("settings", {}))
        if item["type"] == "ufc":
            return {"type": "ufc", "defaults": item.get("settings", {})}
        raise ValueError(f"unsupported instrument type: {item['type']}")

    def list_resources(self, instance_id: str) -> dict[str, Any]:
        item = self._instrument_or_raise(instance_id)
        settings = item.get("settings", {})
        kind = item["type"]
        if kind == "dmm":
            payload = self._dmm_resources()
        elif kind == "opm":
            payload = opm_resource_payload()
        elif kind == "wlm":
            return wlm_resource_payload(settings)
        elif kind == "ufc":
            payload = self._ufc_resources()
        else:
            raise ValueError(f"unsupported instrument type: {kind}")

        with self._device_scan_lock:
            count = 0
            details = {resource_key(detail["resource"]): detail for detail in payload.get("resource_details", [])}
            for key, resource in {resource_key(resource): resource for resource in payload["resources"]}.items():
                device = {"id": key, "status": "detected", "identification": "", **identity_fields("")}
                query = None
                if kind == "opm":
                    detail = details.get(key, {})
                    if detail.get("available"):
                        device.update(identity_fields(",".join(detail.get(field, "") for field in ("manufacturer", "model", "serial"))))
                elif resource.upper().startswith(("USB", "TCPIP")) and resource.upper().endswith(("::INSTR", "::SOCKET")):
                    query = lambda address=resource: _visa_identity(pyvisa.ResourceManager(), address)
                self._identify_device(device, query)
                if device["type"] == kind and device["status"] in {"available", "in_use"}:
                    count += 1
            payload["valid_count"] = count
        return payload

    def check_connection(
        self,
        instance_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        item = self._instrument_or_raise(instance_id)
        controller = self._ensure_controller(item)
        settings = merge_dicts(item.get("settings", {}), payload)
        resource = self._active_resource_key(item["type"], settings)
        reserved_resource = False
        with self._lock:
            if controller.is_running() or instance_id in self._connection_checks:
                raise RuntimeError("Instrument is busy")
            if resource:
                for active_id, active_resource in self._active_resources.items():
                    if active_id != instance_id and active_resource == resource:
                        raise RuntimeError("Another running instrument is already using this resource")
                self._active_resources[instance_id] = resource
                reserved_resource = True
            self._connection_checks.add(instance_id)

        try:
            return self._probe_connection(item["type"], settings)
        finally:
            with self._lock:
                self._connection_checks.discard(instance_id)
                if (
                    reserved_resource
                    and self._active_resources.get(instance_id) == resource
                ):
                    self._active_resources.pop(instance_id, None)

    def start(self, instance_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = self._instrument_or_raise(instance_id)
        controller = self._ensure_controller(item)
        merged = merge_dicts(item.get("settings", {}), payload)
        merged["instrument_instance_id"] = instance_id
        resource = self._active_resource_key(item["type"], merged)
        resource_reserved = False
        with self._lock:
            if (
                controller.is_running()
                or instance_id in self._active_resources
                or instance_id in self._connection_checks
            ):
                raise RuntimeError("Instrument acquisition is already running")
            if resource:
                for active_id, active_resource in self._active_resources.items():
                    if active_id != instance_id and active_resource == resource:
                        raise RuntimeError("Another running instrument is already using this resource")
                self._active_resources[instance_id] = resource
                resource_reserved = True
        try:
            return controller.start_acquisition(merged)  # type: ignore[union-attr]
        except Exception:
            if resource_reserved:
                with self._lock:
                    if self._active_resources.get(instance_id) == resource:
                        self._active_resources.pop(instance_id, None)
            raise

    def stop(self, instance_id: str) -> dict[str, Any]:
        item = self._instrument_or_raise(instance_id)
        return self._ensure_controller(item).stop_acquisition()

    def active_library_files(self) -> tuple[Path, ...]:
        self._ensure_configured_controllers()
        paths = []
        for controller in list(self._controllers.values()):
            path = controller.active_library_file()
            if path is not None:
                paths.append(path)
        return tuple(paths)

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def publish(self, event: str, data: dict[str, Any]) -> None:
        item = {"event": event, "data": data}
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(item)

    def shutdown(self) -> None:
        # Start all stops before waiting for any counter to drain its buffer.
        for controller in list(self._controllers.values()):
            controller.stop_acquisition()
        for instance_id in list(self._controllers):
            self._remove_controller(instance_id)

    def _ensure_configured_controllers(self) -> None:
        instruments = self._load_instruments()
        known_ids = {str(item["id"]) for item in instruments}
        for item in instruments:
            self._ensure_controller(item)
        for instance_id in list(self._controllers):
            if instance_id not in known_ids:
                self._remove_controller(instance_id)

    def _ensure_controller(self, item: dict[str, Any]) -> BackendController | DmmController | OpmController | WlmController:
        instance_id = str(item["id"])
        with self._lock:
            controller = self._controllers.get(instance_id)
            if controller is not None:
                return controller
            kind = str(item["type"])

            def on_event(event: str, data: dict[str, Any]) -> None:
                with self._lock:
                    if self._controllers.get(instance_id) is not controller:
                        return
                    if event in {"done", "error"}:
                        self._active_resources.pop(instance_id, None)
                self.publish("instrument", {
                    "instrument_id": instance_id,
                    "instrument_type": kind,
                    "event": event,
                    "data": data,
                })

            if kind == "dmm":
                controller = DmmController(on_event)
            elif kind == "ufc":
                controller = BackendController(on_event)
            elif kind == "opm":
                controller = OpmController(on_event)
            elif kind == "wlm":
                controller = WlmController(on_event)
            else:
                raise ValueError(f"unsupported instrument type: {kind}")
            self._controllers[instance_id] = controller
            return controller

    def _remove_controller(self, instance_id: str) -> None:
        with self._lock:
            controller = self._controllers.pop(instance_id, None)
            self._active_resources.pop(instance_id, None)
            self._connection_checks.discard(instance_id)
        if controller is not None:
            controller.shutdown()

    def _load_instruments(self) -> list[dict[str, Any]]:
        return list(self.config_store.load().get("instruments", []))

    def _instrument_or_raise(self, instance_id: str) -> dict[str, Any]:
        return self._find_instrument(self._load_instruments(), instance_id)

    @staticmethod
    def _find_instrument(instruments: list[dict[str, Any]], instance_id: str) -> dict[str, Any]:
        for item in instruments:
            if item.get("id") == instance_id:
                return item
        raise KeyError(f"unknown instrument: {instance_id}")

    @staticmethod
    def _public_instrument(item: dict[str, Any]) -> dict[str, Any]:
        return {**item, "display_name": item.get("display_name", "")}

    @staticmethod
    def _ufc_resources() -> dict[str, Any]:
        try:
            resources = list(list_visa_resources())
            error = None
        except Exception as exc:
            resources = []
            error = str(exc)
        return {"resources": resources, "error": error}

    @staticmethod
    def _dmm_resources() -> dict[str, Any]:
        try:
            resources = list(VisaInstrumentClient().discover_resources())
            error = None
        except Exception as exc:
            resources = []
            error = str(exc)
        return {"resources": resources, "error": error}

    @staticmethod
    def _probe_connection(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind == "ufc":
            resource = str(payload.get("resource", "") or "").strip()
            if not resource:
                raise ValueError("Choose or enter a frequency counter VISA resource.")
            client = Keysight53230A()
            try:
                client.configure(CounterConfig(resource=resource))
                identity = client.connect()
                if identity == resource:
                    raise RuntimeError(
                        f"Connected to {resource}, but the instrument did not return an identity."
                    )
            finally:
                client.close()
            return {
                "connected": True,
                "identity": str(identity),
                "resource": resource,
            }

        if kind == "dmm":
            resource = resolve_dmm_resource(payload.get("resource", ""))
            client = VisaInstrumentClient()
            try:
                identity = client.connect(resource)
            finally:
                client.close()
            return {
                "connected": True,
                "identity": identity.raw,
                "resource": resource,
            }

        if kind == "opm":
            config = PowerMeterConfig.from_payload(payload)
            client = TlpmxPowerMeterClient()
            try:
                identity = client.connect(config)
            finally:
                client.close()
            return {
                "connected": True,
                "identity": identity.raw,
                "resource": config.resource,
            }

        if kind == "wlm":
            config = WavelengthMeterConfig.from_payload(payload)
            client = BristolWavelengthMeterClient()
            identity = _bounded_resource_probe(client, config)
            return {
                "connected": True,
                "identity": identity.raw,
                "resource": config.resource,
            }

        raise ValueError(f"unsupported instrument type: {kind}")

    @staticmethod
    def _active_resource_key(kind: str, payload: dict[str, Any]) -> str | None:
        if kind in {"ufc", "opm"}:
            resource = str(payload.get("resource", "") or "").strip()
            return resource_key(resource) if resource else None
        if kind == "dmm":
            return resource_key(resolve_dmm_resource(payload.get("resource", "")))
        if kind == "wlm":
            config = WavelengthMeterConfig.from_payload(payload)
            canonical_resource = canonicalize_wlm_resource(config.resource)
            return canonical_resource
        raise ValueError(f"unsupported instrument type: {kind}")


__all__ = ["InstrumentManager", "INSTRUMENT_TYPES"]
