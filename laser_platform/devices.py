"""USB instrument inventory; identity queries never configure or start a measurement."""

from __future__ import annotations

import ipaddress
import json
import subprocess
import sys
from typing import Any, Callable

import pyvisa
from pyvisa.rname import ResourceName

from laser_platform.visa_transport import configure_visa_termination

from laser_platform.dmm.models import dmm_model_profile
from laser_platform.opm.backend import opm_resource_payload
from laser_platform.wlm.backend import _bounded_resource_probe
from laser_platform.wlm.bristol import BristolWavelengthMeterClient
from laser_platform.wlm.models import WLM_USB_RESOURCE, WavelengthMeterConfig


IDENTITY_TIMEOUT_MS = 1500
IDENTITY_FIELDS = ("manufacturer", "model", "serial", "firmware", "identity", "type")


def resource_key(resource: str) -> str:
    """Match USB aliases across VISA/TLPMX without changing the address used for I/O."""
    value = resource.strip()
    if value.upper().startswith("USB"):
        try:
            parsed = ResourceName.from_string(value.upper())
            numbers = [int(part, 16 if part.lower().startswith("0x") else 10)
                       for part in (parsed.manufacturer_id, parsed.model_code)]
            return f"USB::{numbers[0]}::{numbers[1]}::{parsed.serial_number.casefold()}::{int(parsed.usb_interface_number)}"
        except (ValueError, AttributeError):
            return value.casefold()
    return value


def identity_fields(raw: str) -> dict[str, str]:
    parts = [part.strip() for part in raw.strip().split(",", 3)]
    parts += [""] * (4 - len(parts))
    manufacturer, model, serial, firmware = parts
    if model.casefold() in {"unknown", "n/a", "?", "--"}:
        model = ""
    kind = ""
    vendor = manufacturer.upper()
    if any(name in vendor for name in ("KEYSIGHT", "AGILENT", "HEWLETT")) or vendor == "HP":
        if dmm_model_profile(model):
            kind = "dmm"
        elif model.upper() in {"53220A", "53230A"}:
            kind = "ufc"
    elif "THORLABS" in vendor and model.upper().startswith("PM"):
        kind = "opm"
    elif "BRISTOL" in vendor and model.startswith(("671", "771")):
        kind = "wlm"
    return dict(zip(IDENTITY_FIELDS, (manufacturer, model, serial, firmware, raw.strip(), kind)))


def bristol_usb_present() -> bool:
    if sys.platform != "win32":
        return False
    # Inspect the route, not just the saved endpoint: a disconnected meter is not a device.
    script = r"""
$ErrorActionPreference = 'Stop'
$allRoutes = @(Get-NetRoute -AddressFamily IPv4)
$rows = @(Get-CimInstance Win32_NetworkAdapter -Filter 'NetConnectionStatus=2' | Where-Object { $_.PNPDeviceID -like 'USB\*' } | ForEach-Object {
    $adapter = $_
    $routes = @($allRoutes | Where-Object { $_.InterfaceIndex -eq $adapter.InterfaceIndex } | Select-Object DestinationPrefix,NextHop)
    [PSCustomObject]@{pnp_id=$_.PNPDeviceID; routes=$routes}
})
ConvertTo-Json -InputObject $rows -Compress -Depth 4
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=5,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    target = ipaddress.ip_address(WLM_USB_RESOURCE.split(":")[0])
    for adapter in json.loads(result.stdout):
        if not str(adapter.get("pnp_id") or "").upper().startswith("USB\\"):
            continue
        for route in adapter["routes"]:
            network = ipaddress.ip_network(route["DestinationPrefix"], strict=False)
            if route["NextHop"] == "0.0.0.0" and network.prefixlen > 0 and target in network:
                return True
    return False


def _visa_identity(manager: Any, resource: str) -> dict[str, str]:
    connection = manager.open_resource(
        resource, access_mode=pyvisa.constants.AccessModes.exclusive_lock,
        open_timeout=IDENTITY_TIMEOUT_MS,
    )
    try:
        connection.timeout = IDENTITY_TIMEOUT_MS
        configure_visa_termination(connection)
        return identity_fields(str(connection.query("*IDN?")))
    except (TimeoutError, pyvisa.errors.VisaIOError) as exc:
        if isinstance(exc, pyvisa.errors.VisaIOError) and exc.error_code != pyvisa.constants.StatusCode.error_timeout:
            raise
        return {"identification": f"Identity query failed: {exc}"}
    finally:
        connection.close()


def _bristol_identity() -> dict[str, str]:
    identity = _bounded_resource_probe(BristolWavelengthMeterClient(), WavelengthMeterConfig())
    # The acquisition driver permits an endpoint-only fallback; it is not a discovered identity.
    return identity_fields(identity.raw) if "," in identity.raw else identity_fields("")


def scan_usb_devices(identify: Callable[[dict[str, Any], Callable | None], None]) -> dict[str, Any]:
    devices: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    visa_resources: dict[str, str] = {}
    manager = None

    def add(resource: str, transport: str = "USB") -> dict[str, Any]:
        key = resource_key(resource)
        if key not in devices:
            devices[key] = {
                "id": key, "resource": resource, "transport": transport,
                **dict.fromkeys(IDENTITY_FIELDS, ""),
                "status": "detected", "identification": "",
            }
        return devices[key]

    try:
        # PyVISA shares this manager across clients and closes it at process exit.
        manager = pyvisa.ResourceManager()
        for resource in manager.list_resources("USB?*"):
            if not resource.upper().startswith("USB"):
                continue
            device = add(resource)
            if resource.upper().endswith("::INSTR"):
                visa_resources[device["id"]] = resource
    except Exception as exc:
        warnings.append(f"VISA discovery: {exc}")

    power_meters = opm_resource_payload()
    for item in power_meters["resource_details"]:
        if not item["resource"].upper().startswith("USB"):
            continue
        device = add(item["resource"])
        device.update(identity_fields(",".join(item.get(field, "") for field in ("manufacturer", "model", "serial"))))
        if not item["available"]:
            device["status"] = "in_use"

    try:
        if bristol_usb_present():
            add(WLM_USB_RESOURCE, "USB virtual Ethernet")
    except Exception:
        warnings.append("Bristol USB discovery could not read the local network interfaces.")

    for key, device in devices.items():
        query = None
        if device["transport"] == "USB virtual Ethernet":
            query = _bristol_identity
        elif not device["model"] and key in visa_resources:
            query = lambda address=visa_resources[key]: _visa_identity(manager, address)
        identify(device, query)

    return {"devices": sorted(devices.values(), key=lambda item: (not bool(item["model"]), item["model"], item["id"])),
            "warnings": warnings}
