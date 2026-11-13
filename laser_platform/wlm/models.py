from __future__ import annotations

import ipaddress
import re
from dataclasses import asdict, dataclass
from typing import Any, ClassVar
from urllib.parse import urlsplit

WLM_USB_RESOURCE = "10.199.199.1:23"
DEFAULT_WLM_PORT = 23
DEFAULT_WLM_CONNECTION_MODE = "usb"
WLM_CONNECTION_MODES = ("usb", "ethernet")
WLM_OPERATION_TIMEOUT_S = 5.0
# Bristol 671 Series published measurement rates: 2.5 Hz for IR/MIR,
# 4 Hz for 671A VIS/NIR/NIR2, and 10 Hz for 671B VIS/NIR/NIR2.
WLM_SAFE_FALLBACK_SAMPLE_RATE_HZ = 2.5
WLM_671A_FAST_SAMPLE_RATE_HZ = 4.0
WLM_671B_FAST_SAMPLE_RATE_HZ = 10.0


@dataclass(slots=True, frozen=True)
class WavelengthMeterIdentity:
    manufacturer: str
    model: str
    serial: str
    firmware: str
    raw: str


@dataclass(slots=True, frozen=True)
class WavelengthMeterResource:
    resource: str
    model: str = ""
    serial: str = ""
    manufacturer: str = ""
    firmware: str = ""
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WavelengthMeterConfig:
    connection_mode: str = DEFAULT_WLM_CONNECTION_MODE
    resource: str = WLM_USB_RESOURCE
    ethernet_resource: str = ""

    operation_timeout_s: ClassVar[float] = WLM_OPERATION_TIMEOUT_S

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WavelengthMeterConfig:
        connection_mode = str(
            payload.get("connection_mode", DEFAULT_WLM_CONNECTION_MODE)
            or DEFAULT_WLM_CONNECTION_MODE
        ).strip().casefold()
        ethernet_resource = str(
            payload.get("ethernet_resource", "") or ""
        ).strip()

        if connection_mode == "usb":
            resource = WLM_USB_RESOURCE
        else:
            resource = ethernet_resource

        config = cls(
            connection_mode=connection_mode,
            resource=resource,
            ethernet_resource=ethernet_resource,
        )
        config.validate()
        return config

    @property
    def canonical_resource(self) -> str:
        return canonicalize_wlm_resource(self.resource)

    def validate(self) -> None:
        if self.connection_mode not in WLM_CONNECTION_MODES:
            raise ValueError("Connection mode must be 'usb' or 'ethernet'.")
        if not self.resource:
            if self.connection_mode == "ethernet":
                raise ValueError("Enter the Bristol wavelength meter Ethernet endpoint.")
            raise ValueError("Enter a Bristol wavelength meter network endpoint.")
        if self.connection_mode == "usb" and self.resource != WLM_USB_RESOURCE:
            raise ValueError(
                f"USB wavelength meter connections use {WLM_USB_RESOURCE}."
            )
        canonicalize_wlm_resource(self.resource)

    def as_dict(self) -> dict[str, Any]:
        return {
            "connection_mode": self.connection_mode,
            "resource": self.resource,
            "ethernet_resource": self.ethernet_resource,
        }


@dataclass(slots=True, frozen=True)
class WavelengthSample:
    elapsed_s: float
    wavelength_nm: float


def safe_wlm_sample_rate_hz(
    identity: WavelengthMeterIdentity,
    wavelength_nm: float | None = None,
) -> float:
    """Return the fastest unambiguous published measurement rate."""

    identity_tokens = set(
        re.findall(
            r"[A-Z0-9]+",
            f"{identity.model} {identity.raw}".upper(),
        )
    )
    if identity_tokens & {"IR", "MIR"}:
        return WLM_SAFE_FALLBACK_SAMPLE_RATE_HZ

    optical_range_is_fast = bool(
        identity_tokens & {"VIS", "NIR", "NIR2"}
    )
    if wavelength_nm is not None:
        optical_range_is_fast = optical_range_is_fast or (
            375.0 <= float(wavelength_nm) < 1000.0
        )
    if not optical_range_is_fast:
        return WLM_SAFE_FALLBACK_SAMPLE_RATE_HZ
    if "671B" in identity_tokens:
        return WLM_671B_FAST_SAMPLE_RATE_HZ
    if "671A" in identity_tokens:
        return WLM_671A_FAST_SAMPLE_RATE_HZ
    return WLM_SAFE_FALLBACK_SAMPLE_RATE_HZ


def canonicalize_wlm_resource(resource: str) -> str:
    """Return a stable endpoint key for equivalent Bristol Telnet resources."""

    value = str(resource or "").strip()
    if not value:
        raise ValueError("Enter a Bristol wavelength meter network endpoint.")

    host, port = split_wlm_resource(value)
    normalized_host = _canonical_host(host)
    rendered_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    return f"{rendered_host}:{port}"


def split_wlm_resource(resource: str) -> tuple[str, int]:
    """Parse host, host:port, or telnet://host:port into connection arguments."""

    value = str(resource or "").strip()
    if not value:
        raise ValueError("Enter a Bristol wavelength meter network endpoint.")

    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() != "telnet":
            raise ValueError("Wavelength meter resource must use the telnet:// scheme.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Wavelength meter resource must not contain credentials.")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Wavelength meter resource must contain only a host and port.")
        host = parsed.hostname or ""
        try:
            port = parsed.port or DEFAULT_WLM_PORT
        except ValueError as exc:
            raise ValueError("Wavelength meter resource has an invalid port.") from exc
        return _validated_endpoint(host, port)

    if value.startswith("["):
        closing = value.find("]")
        if closing < 0:
            raise ValueError("Wavelength meter IPv6 endpoints must close the '[' bracket.")
        host = value[1:closing]
        suffix = value[closing + 1 :]
        if not suffix:
            port = DEFAULT_WLM_PORT
        elif suffix.startswith(":") and suffix[1:]:
            port = _parse_port(suffix[1:])
        else:
            raise ValueError("Wavelength meter resource has an invalid bracketed endpoint.")
        return _validated_endpoint(host, port)

    colon_count = value.count(":")
    if colon_count == 0:
        return _validated_endpoint(value, DEFAULT_WLM_PORT)
    if colon_count == 1:
        host, port_text = value.rsplit(":", 1)
        return _validated_endpoint(host, _parse_port(port_text))

    try:
        ipv6 = ipaddress.IPv6Address(value)
    except ValueError as exc:
        raise ValueError(
            "Wavelength meter IPv6 endpoints with a port must use [address]:port."
        ) from exc
    return _validated_endpoint(str(ipv6), DEFAULT_WLM_PORT)


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Wavelength meter resource port must be an integer.") from exc
    return port


def _validated_endpoint(host: str, port: int) -> tuple[str, int]:
    host = str(host or "").strip()
    if not host or any(character.isspace() for character in host):
        raise ValueError("Wavelength meter resource must include a valid host.")
    if not 1 <= int(port) <= 65535:
        raise ValueError("Wavelength meter resource port must be between 1 and 65535.")
    return host, int(port)


def _canonical_host(host: str) -> str:
    value = host.strip()
    try:
        return ipaddress.ip_address(value).compressed.casefold()
    except ValueError:
        normalized = value.rstrip(".").casefold()
        if not normalized:
            raise ValueError("Wavelength meter resource must include a valid host.")
        return normalized


__all__ = [
    "DEFAULT_WLM_CONNECTION_MODE",
    "DEFAULT_WLM_PORT",
    "WLM_671A_FAST_SAMPLE_RATE_HZ",
    "WLM_671B_FAST_SAMPLE_RATE_HZ",
    "WLM_CONNECTION_MODES",
    "WLM_OPERATION_TIMEOUT_S",
    "WLM_SAFE_FALLBACK_SAMPLE_RATE_HZ",
    "WLM_USB_RESOURCE",
    "WavelengthMeterConfig",
    "WavelengthMeterIdentity",
    "WavelengthMeterResource",
    "WavelengthSample",
    "canonicalize_wlm_resource",
    "safe_wlm_sample_rate_hz",
    "split_wlm_resource",
]
