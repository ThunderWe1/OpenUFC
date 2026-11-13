from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar

DISPLAY_UNITS = ("W", "mW", "dBm")
OPM_OPERATION_TIMEOUT_MS = 5000
# Conservative TLPMX cadence aligned with the PM100D numerical refresh rate.
OPM_SAFE_SAMPLE_RATE_HZ = 10.0
POWER_RANGE_OPTIONS: tuple[tuple[str, float], ...] = (
    ("100 nW", 1e-7),
    ("1 uW", 1e-6),
    ("10 uW", 1e-5),
    ("100 uW", 1e-4),
    ("1 mW", 1e-3),
    ("10 mW", 1e-2),
    ("100 mW", 1e-1),
    ("1 W", 1.0),
    ("10 W", 10.0),
)


@dataclass(slots=True, frozen=True)
class PowerMeterIdentity:
    manufacturer: str
    model: str
    serial: str
    firmware: str
    raw: str


@dataclass(slots=True, frozen=True)
class PowerMeterResource:
    resource: str
    model: str = ""
    serial: str = ""
    manufacturer: str = ""
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class PowerMeterSensor:
    name: str
    serial: str
    calibration: str
    sensor_type: int
    sensor_subtype: int
    flags: int

    @property
    def is_power_capable(self) -> bool:
        return bool(self.flags & 0x0001)

    @property
    def wavelength_settable(self) -> bool:
        return bool(self.flags & 0x0020)


@dataclass(slots=True)
class PowerMeterConfig:
    resource: str = ""
    wavelength_nm: float = 852.0
    display_unit: str = "mW"
    autorange: bool = True
    manual_range_w: float = 0.01
    channel: int = 1
    operation_timeout_ms: ClassVar[int] = OPM_OPERATION_TIMEOUT_MS

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> PowerMeterConfig:
        display_unit = str(payload.get("display_unit", "mW") or "mW")
        display_unit = {"w": "W", "mw": "mW", "dbm": "dBm"}.get(display_unit.lower(), display_unit)
        config = cls(
            resource=str(payload.get("resource", "") or "").strip(),
            wavelength_nm=float(payload.get("wavelength_nm", 852.0)),
            display_unit=display_unit,
            autorange=bool(payload.get("autorange", True)),
            manual_range_w=float(payload.get("manual_range_w", 0.01)),
            channel=int(payload.get("channel", 1)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.resource:
            raise ValueError("Choose or enter a Thorlabs optical power meter resource.")
        if self.display_unit not in DISPLAY_UNITS:
            raise ValueError("Display unit must be W, mW, or dBm.")
        if self.channel != 1:
            raise ValueError("Optical Power Meter currently supports channel 1 only.")
        if self.wavelength_nm <= 0:
            raise ValueError("Wavelength must be greater than zero.")
        if self.manual_range_w <= 0:
            raise ValueError("Manual power range must be greater than zero.")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class PowerSample:
    elapsed_s: float
    power_w: float


__all__ = [
    "DISPLAY_UNITS",
    "OPM_OPERATION_TIMEOUT_MS",
    "OPM_SAFE_SAMPLE_RATE_HZ",
    "POWER_RANGE_OPTIONS",
    "PowerMeterConfig",
    "PowerMeterIdentity",
    "PowerMeterResource",
    "PowerMeterSensor",
    "PowerSample",
]
