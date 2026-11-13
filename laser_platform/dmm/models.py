from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


DMM_OPERATION_TIMEOUT_MS = 5000


class MeasurementFunction(str, Enum):
    VOLT_DC = "VOLT:DC"
    VOLT_AC = "VOLT:AC"
    CURR_DC = "CURR:DC"
    CURR_AC = "CURR:AC"
    RES = "RES"

    @property
    def label(self) -> str:
        return _MEASUREMENT_INFO[self]["label"]

    @property
    def unit(self) -> str:
        return _MEASUREMENT_INFO[self]["unit"]

    @property
    def supports_nplc(self) -> bool:
        return bool(_MEASUREMENT_INFO[self]["supports_nplc"])

    @property
    def is_current(self) -> bool:
        return self in {MeasurementFunction.CURR_DC, MeasurementFunction.CURR_AC}

    @property
    def range_options(self) -> tuple[tuple[str, float], ...]:
        return tuple(_MEASUREMENT_INFO[self]["range_options"])

    @property
    def nplc_options(self) -> tuple[float, ...]:
        return tuple(_MEASUREMENT_INFO[self].get("nplc_options", ()))


RangeOptions = tuple[tuple[str, float], ...]


_DC_VOLTAGE_RANGES: RangeOptions = (
    ("100 mV", 0.1),
    ("1 V", 1.0),
    ("10 V", 10.0),
    ("100 V", 100.0),
    ("1000 V", 1000.0),
)
_AC_VOLTAGE_RANGES: RangeOptions = (
    ("100 mV", 0.1),
    ("1 V", 1.0),
    ("10 V", 10.0),
    ("100 V", 100.0),
    ("750 V", 750.0),
)
_DC_CURRENT_RANGES_LOW: RangeOptions = (
    ("1 uA", 0.000001),
    ("10 uA", 0.00001),
)
_CURRENT_RANGES_3A: RangeOptions = (
    ("100 uA", 0.0001),
    ("1 mA", 0.001),
    ("10 mA", 0.01),
    ("100 mA", 0.1),
    ("1 A", 1.0),
    ("3 A", 3.0),
)
_CURRENT_RANGE_10A: RangeOptions = (("10 A (10 A terminal)", 10.0),)
_RESISTANCE_RANGES: RangeOptions = (
    ("100 Ohm", 100.0),
    ("1 kOhm", 1000.0),
    ("10 kOhm", 10000.0),
    ("100 kOhm", 100000.0),
    ("1 MOhm", 1000000.0),
    ("10 MOhm", 10000000.0),
    ("100 MOhm", 100000000.0),
)
_RESISTANCE_RANGE_1G: RangeOptions = (("1 GOhm", 1000000000.0),)
_COMMON_NPLC_OPTIONS = (0.02, 0.2, 1.0, 10.0, 100.0)


_MEASUREMENT_INFO: dict[MeasurementFunction, dict[str, Any]] = {
    MeasurementFunction.VOLT_DC: {
        "label": "DC Voltage",
        "unit": "V",
        "supports_nplc": True,
        "default_interval_ms": 400,
        "range_options": _DC_VOLTAGE_RANGES,
        "nplc_options": _COMMON_NPLC_OPTIONS,
    },
    MeasurementFunction.VOLT_AC: {
        "label": "AC Voltage",
        "unit": "V RMS",
        "supports_nplc": False,
        "default_interval_ms": 600,
        "range_options": _AC_VOLTAGE_RANGES,
    },
    MeasurementFunction.CURR_DC: {
        "label": "DC Current",
        "unit": "A",
        "supports_nplc": True,
        "default_interval_ms": 400,
        # The generic list is the union exposed before a connected model is
        # known. DmmModelProfile supplies the authoritative per-model list.
        "range_options": _DC_CURRENT_RANGES_LOW + _CURRENT_RANGES_3A + _CURRENT_RANGE_10A,
        "nplc_options": _COMMON_NPLC_OPTIONS,
    },
    MeasurementFunction.CURR_AC: {
        "label": "AC Current",
        "unit": "A RMS",
        "supports_nplc": False,
        "default_interval_ms": 600,
        "range_options": _CURRENT_RANGES_3A + _CURRENT_RANGE_10A,
    },
    MeasurementFunction.RES: {
        "label": "Resistance",
        "unit": "Ohm",
        "supports_nplc": True,
        "default_interval_ms": 450,
        "range_options": _RESISTANCE_RANGES + _RESISTANCE_RANGE_1G,
        "nplc_options": _COMMON_NPLC_OPTIONS,
    },
}


@dataclass(frozen=True, slots=True)
class DmmModelProfile:
    model: str
    range_options: Mapping[MeasurementFunction, RangeOptions]
    supports_ascii_format: bool
    current_terminals_a: tuple[int, ...] = (3,)

    @property
    def supports_10a_terminal(self) -> bool:
        return 10 in self.current_terminals_a

    def ranges_for(self, function: MeasurementFunction) -> RangeOptions:
        return tuple(self.range_options[function])

    def supports_range(self, function: MeasurementFunction, range_value: float) -> bool:
        return any(
            math.isclose(float(range_value), value, rel_tol=1e-12, abs_tol=1e-15)
            for _, value in self.ranges_for(function)
        )

    def validate_measurement(self, config: "MeasurementConfig") -> None:
        if config.autorange:
            return
        if config.range_value is None:
            raise ValueError("Manual range must be a positive number.")
        if self.supports_range(config.function, config.range_value):
            return
        allowed = ", ".join(label for label, _ in self.ranges_for(config.function))
        raise ValueError(
            f"{config.range_value:g} is not a supported {config.function.label} range "
            f"for {self.model}. Choose one of: {allowed}."
        )


def _profile_ranges(
    *,
    dc_current: RangeOptions,
    ac_current: RangeOptions,
    resistance: RangeOptions,
) -> dict[MeasurementFunction, RangeOptions]:
    return {
        MeasurementFunction.VOLT_DC: _DC_VOLTAGE_RANGES,
        MeasurementFunction.VOLT_AC: _AC_VOLTAGE_RANGES,
        MeasurementFunction.CURR_DC: dc_current,
        MeasurementFunction.CURR_AC: ac_current,
        MeasurementFunction.RES: resistance,
    }


_RANGES_3A = _profile_ranges(
    dc_current=_CURRENT_RANGES_3A,
    ac_current=_CURRENT_RANGES_3A,
    resistance=_RESISTANCE_RANGES,
)
_RANGES_3A_WITH_1G = _profile_ranges(
    dc_current=_CURRENT_RANGES_3A,
    ac_current=_CURRENT_RANGES_3A,
    resistance=_RESISTANCE_RANGES + _RESISTANCE_RANGE_1G,
)
_RANGES_10A = _profile_ranges(
    dc_current=_CURRENT_RANGES_3A + _CURRENT_RANGE_10A,
    ac_current=_CURRENT_RANGES_3A + _CURRENT_RANGE_10A,
    resistance=_RESISTANCE_RANGES,
)
_RANGES_ADVANCED_TRUEVOLT = _profile_ranges(
    dc_current=_DC_CURRENT_RANGES_LOW + _CURRENT_RANGES_3A + _CURRENT_RANGE_10A,
    ac_current=_CURRENT_RANGES_3A + _CURRENT_RANGE_10A,
    resistance=_RESISTANCE_RANGES + _RESISTANCE_RANGE_1G,
)


DMM_MODEL_PROFILES: dict[str, DmmModelProfile] = {
    "34410A": DmmModelProfile(
        model="34410A",
        range_options=_RANGES_3A_WITH_1G,
        supports_ascii_format=True,
    ),
    "34411A": DmmModelProfile(
        model="34411A",
        range_options=_RANGES_3A_WITH_1G,
        supports_ascii_format=True,
    ),
    "34460A": DmmModelProfile(
        model="34460A",
        range_options=_RANGES_3A,
        supports_ascii_format=False,
    ),
    "34461A": DmmModelProfile(
        model="34461A",
        range_options=_RANGES_10A,
        supports_ascii_format=False,
        current_terminals_a=(3, 10),
    ),
    "34465A": DmmModelProfile(
        model="34465A",
        range_options=_RANGES_ADVANCED_TRUEVOLT,
        supports_ascii_format=True,
        current_terminals_a=(3, 10),
    ),
    "34470A": DmmModelProfile(
        model="34470A",
        range_options=_RANGES_ADVANCED_TRUEVOLT,
        supports_ascii_format=True,
        current_terminals_a=(3, 10),
    ),
}
SUPPORTED_DMM_MODELS = tuple(DMM_MODEL_PROFILES)


def normalize_dmm_model(model: str) -> str:
    return str(model or "").strip().upper()


def dmm_model_profile(model: str) -> DmmModelProfile | None:
    return DMM_MODEL_PROFILES.get(normalize_dmm_model(model))


def resolve_dmm_resource(resource: str) -> str:
    target = resource.strip()
    if not target:
        raise ValueError("Choose or enter a DMM VISA resource or host/IP.")
    return target if "::" in target else f"TCPIP0::{target}::inst0::INSTR"


@dataclass(slots=True)
class MeasurementConfig:
    function: MeasurementFunction = MeasurementFunction.VOLT_DC
    autorange: bool = True
    range_value: float | None = None
    nplc: float = 1.0

    def validate(self) -> None:
        if not self.autorange:
            if self.range_value is None or self.range_value <= 0:
                raise ValueError("Manual range must be a positive number.")
        if self.nplc <= 0:
            raise ValueError("NPLC must be greater than zero.")

    @property
    def interval_ms(self) -> int:
        if self.function.supports_nplc:
            plc_window_ms = self.nplc * 20.0
            return max(100, int(round(plc_window_ms * 4.0 + 160.0)))
        return int(_MEASUREMENT_INFO[self.function]["default_interval_ms"])

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["measurement_function"] = payload.pop("function").value
        payload["interval_ms"] = self.interval_ms
        return payload


@dataclass(slots=True)
class SampleRecord:
    elapsed_s: float
    value: float
    unit: str
    function: MeasurementFunction
