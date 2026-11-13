from __future__ import annotations

import ctypes
import logging
import os
import struct
from pathlib import Path
from typing import Any, Callable, Iterable

from laser_platform.opm.client import (
    PowerMeterDriverUnavailable,
    PowerMeterError,
)
from laser_platform.opm.models import (
    PowerMeterConfig,
    PowerMeterIdentity,
    PowerMeterResource,
    PowerMeterSensor,
)


TLPM_DEFAULT_CHANNEL = 1
TLPM_ATTR_MIN_VAL = 1
TLPM_ATTR_MAX_VAL = 2
TLPM_POWER_UNIT_WATT = 0
TLPM_AUTORANGE_POWER_OFF = 0
TLPM_AUTORANGE_POWER_ON = 1
TLPM_BUFFER_SIZE = 256
TLPM_ERROR_BUFFER_SIZE = 512
LOGGER = logging.getLogger(__name__)


class TlpmxPowerMeterClient:
    """Small ctypes adapter for the TLPMX calls used by OpenUFC."""

    def __init__(
        self,
        dll: Any | None = None,
        *,
        dll_loader: Callable[[str], Any] | None = None,
        candidate_paths: Iterable[str | Path] | None = None,
    ) -> None:
        self._dll = dll
        self._dll_loader = dll_loader or ctypes.CDLL
        self._candidate_paths = tuple(str(path) for path in candidate_paths) if candidate_paths is not None else None
        self._session: ctypes.c_long | None = None
        self._identity: PowerMeterIdentity | None = None
        self._resource_name: str | None = None
        self._sensor: PowerMeterSensor | None = None

    @property
    def identity(self) -> PowerMeterIdentity | None:
        return self._identity

    @property
    def resource_name(self) -> str | None:
        return self._resource_name

    @property
    def sensor(self) -> PowerMeterSensor | None:
        return self._sensor

    def discover_resources(self) -> list[PowerMeterResource]:
        self._ensure_dll()
        session = ctypes.c_long(0)
        try:
            count = ctypes.c_uint32(0)
            self._checked_call("TLPMX_findRsrc", session, ctypes.byref(count), session=session)
            resources: list[PowerMeterResource] = []
            for index in range(int(count.value)):
                resource_name = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
                model = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
                serial = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
                manufacturer = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
                available = ctypes.c_int16(0)
                driver_index = ctypes.c_uint32(index)
                self._checked_call(
                    "TLPMX_getRsrcName",
                    session,
                    driver_index,
                    resource_name,
                    session=session,
                )
                self._checked_call(
                    "TLPMX_getRsrcInfo",
                    session,
                    driver_index,
                    model,
                    serial,
                    manufacturer,
                    ctypes.byref(available),
                    session=session,
                )
                resources.append(
                    PowerMeterResource(
                        resource=_buffer_text(resource_name),
                        model=_buffer_text(model),
                        serial=_buffer_text(serial),
                        manufacturer=_buffer_text(manufacturer),
                        available=bool(available.value),
                    )
                )
            return resources
        finally:
            self._close_session(session, check=False)

    def connect(self, config: PowerMeterConfig) -> PowerMeterIdentity:
        config.validate()
        self._ensure_dll()
        self.close()

        session = ctypes.c_long(0)
        resource = ctypes.create_string_buffer(config.resource.encode("utf-8"))
        try:
            self._checked_call(
                "TLPMX_init",
                resource,
                ctypes.c_bool(True),
                ctypes.c_bool(False),
                ctypes.byref(session),
                session=session,
            )
            self._session = session
            self._resource_name = config.resource
            self._identity = self._read_identity()
            self._sensor = self._read_sensor(config.channel)
            if not self._sensor.is_power_capable:
                sensor_name = self._sensor.name or "connected sensor"
                raise PowerMeterError(f"{sensor_name} is not a power-capable Thorlabs sensor.")
            if hasattr(self._dll, "TLPMX_setTimeoutValue"):
                self._checked_call(
                    "TLPMX_setTimeoutValue",
                    session,
                    ctypes.c_uint32(config.operation_timeout_ms),
                )
            self._set_watt_unit(config.channel)
            return self._identity
        except Exception:
            self._close_session(session, check=False)
            self._clear_connection()
            raise

    def configure(self, config: PowerMeterConfig) -> None:
        config.validate()
        session = self._require_session()
        sensor = self._sensor
        if sensor is None or not sensor.is_power_capable:
            raise PowerMeterError("No power-capable sensor is connected on channel 1.")

        self._set_watt_unit(config.channel)
        if sensor.wavelength_settable:
            self._checked_call(
                "TLPMX_setWavelength",
                session,
                ctypes.c_double(config.wavelength_nm),
                ctypes.c_uint16(config.channel),
            )

        if config.autorange:
            self._checked_call(
                "TLPMX_setPowerAutoRange",
                session,
                ctypes.c_int16(TLPM_AUTORANGE_POWER_ON),
                ctypes.c_uint16(config.channel),
            )
            return

        minimum_w, maximum_w = self.power_range_limits(config.channel)
        if not minimum_w <= config.manual_range_w <= maximum_w:
            raise ValueError(
                "Manual power range "
                f"{config.manual_range_w:g} W is outside the connected sensor range "
                f"{minimum_w:g} W to {maximum_w:g} W."
            )
        self._checked_call(
            "TLPMX_setPowerAutoRange",
            session,
            ctypes.c_int16(TLPM_AUTORANGE_POWER_OFF),
            ctypes.c_uint16(config.channel),
        )
        self._checked_call(
            "TLPMX_setPowerRange",
            session,
            ctypes.c_double(config.manual_range_w),
            ctypes.c_uint16(config.channel),
        )

    def power_range_limits(self, channel: int = TLPM_DEFAULT_CHANNEL) -> tuple[float, float]:
        session = self._require_session()
        minimum = ctypes.c_double()
        maximum = ctypes.c_double()
        self._checked_call(
            "TLPMX_getPowerRange",
            session,
            ctypes.c_int16(TLPM_ATTR_MIN_VAL),
            ctypes.byref(minimum),
            ctypes.c_uint16(channel),
        )
        self._checked_call(
            "TLPMX_getPowerRange",
            session,
            ctypes.c_int16(TLPM_ATTR_MAX_VAL),
            ctypes.byref(maximum),
            ctypes.c_uint16(channel),
        )
        if minimum.value < 0 or maximum.value <= 0 or minimum.value > maximum.value:
            raise PowerMeterError("TLPMX returned invalid power-range limits for the connected sensor.")
        return float(minimum.value), float(maximum.value)

    def read_once(self) -> float:
        session = self._require_session()
        power_w = ctypes.c_double()
        self._checked_call(
            "TLPMX_measPower",
            session,
            ctypes.byref(power_w),
            ctypes.c_uint16(TLPM_DEFAULT_CHANNEL),
        )
        return float(power_w.value)

    def close(self) -> None:
        session = self._session
        self._clear_connection()
        if session is not None:
            self._close_session(session, check=True)

    def _read_identity(self) -> PowerMeterIdentity:
        session = self._require_session()
        manufacturer = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
        model = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
        serial = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
        firmware = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
        self._checked_call(
            "TLPMX_identificationQuery",
            session,
            manufacturer,
            model,
            serial,
            firmware,
        )
        values = (
            _buffer_text(manufacturer),
            _buffer_text(model),
            _buffer_text(serial),
            _buffer_text(firmware),
        )
        return PowerMeterIdentity(*values, raw=",".join(values))

    def _read_sensor(self, channel: int) -> PowerMeterSensor:
        session = self._require_session()
        name = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
        serial = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
        calibration = ctypes.create_string_buffer(TLPM_BUFFER_SIZE)
        sensor_type = ctypes.c_int16()
        sensor_subtype = ctypes.c_int16()
        flags = ctypes.c_int16()
        self._checked_call(
            "TLPMX_getSensorInfo",
            session,
            name,
            serial,
            calibration,
            ctypes.byref(sensor_type),
            ctypes.byref(sensor_subtype),
            ctypes.byref(flags),
            ctypes.c_uint16(channel),
        )
        return PowerMeterSensor(
            name=_buffer_text(name),
            serial=_buffer_text(serial),
            calibration=_buffer_text(calibration),
            sensor_type=int(sensor_type.value),
            sensor_subtype=int(sensor_subtype.value),
            flags=int(flags.value) & 0xFFFF,
        )

    def _set_watt_unit(self, channel: int) -> None:
        self._checked_call(
            "TLPMX_setPowerUnit",
            self._require_session(),
            ctypes.c_int16(TLPM_POWER_UNIT_WATT),
            ctypes.c_uint16(channel),
        )

    def _ensure_dll(self) -> Any:
        if self._dll is not None:
            return self._dll
        errors: list[str] = []
        candidates = self._candidate_paths or tuple(_default_dll_candidates())
        for candidate in candidates:
            try:
                self._dll = self._dll_loader(candidate)
                return self._dll
            except (OSError, FileNotFoundError) as exc:
                errors.append(f"{candidate}: {exc}")
        detail = "; ".join(errors) if errors else "no TLPMX DLL candidates were available"
        diagnostics = f"Attempted: {detail}"
        LOGGER.warning("TLPMX driver load failed. %s", diagnostics)
        raise PowerMeterDriverUnavailable(
            "TLPMX driver unavailable. Install Thorlabs Optical Power Monitor.",
            details=diagnostics,
        )

    def _checked_call(
        self,
        function_name: str,
        *args: Any,
        session: ctypes.c_long | None = None,
    ) -> int:
        dll = self._ensure_dll()
        function = getattr(dll, function_name, None)
        if function is None:
            raise PowerMeterError(f"Installed TLPMX driver does not provide {function_name}.")
        status = _status_value(function(*args))
        if status < 0:
            active_session = session if session is not None else self._session
            description = self._error_description(status, active_session)
            raise PowerMeterError(f"{function_name} failed ({status}): {description}")
        return status

    def _error_description(self, status: int, session: ctypes.c_long | None) -> str:
        dll = self._dll
        function = getattr(dll, "TLPMX_errorMessage", None) if dll is not None else None
        if function is None:
            return "unknown TLPMX error"
        description = ctypes.create_string_buffer(TLPM_ERROR_BUFFER_SIZE)
        try:
            function(session or ctypes.c_long(0), ctypes.c_int32(status), description)
            return _buffer_text(description) or "unknown TLPMX error"
        except Exception:
            return "unknown TLPMX error"

    def _close_session(self, session: ctypes.c_long, *, check: bool) -> None:
        dll = self._dll
        function = getattr(dll, "TLPMX_close", None) if dll is not None else None
        if function is None:
            return
        try:
            status = _status_value(function(session))
            if check and status < 0:
                raise PowerMeterError(
                    f"TLPMX_close failed ({status}): {self._error_description(status, session)}"
                )
        except PowerMeterError:
            raise
        except Exception:
            if check:
                raise

    def _require_session(self) -> ctypes.c_long:
        if self._session is None or not self._session.value:
            raise PowerMeterError("Optical power meter is not connected.")
        return self._session

    def _clear_connection(self) -> None:
        self._session = None
        self._identity = None
        self._resource_name = None
        self._sensor = None


def _default_dll_candidates() -> list[str]:
    is_64_bit = struct.calcsize("P") == 8
    dll_name = "TLPMX_64.dll" if is_64_bit else "TLPMX_32.dll"
    candidates: list[str] = []
    configured_path = str(os.environ.get("TLPMX_DLL_PATH", "") or "").strip()
    if configured_path:
        candidates.append(configured_path)
    if is_64_bit:
        candidates.extend(
            [
                rf"C:\Program Files\IVI Foundation\VISA\Win64\Bin\{dll_name}",
                rf"C:\Program Files\Thorlabs\Optical Power Monitor\{dll_name}",
            ]
        )
    else:
        candidates.extend(
            [
                rf"C:\Program Files (x86)\IVI Foundation\VISA\WinNT\Bin\{dll_name}",
                rf"C:\Program Files (x86)\Thorlabs\Optical Power Monitor\{dll_name}",
            ]
        )
    candidates.append(dll_name)
    return candidates


def _buffer_text(buffer: Any) -> str:
    raw = bytes(buffer.value) if hasattr(buffer, "value") else bytes(buffer)
    return raw.decode("utf-8", errors="replace").strip()


def _status_value(status: Any) -> int:
    if status is None:
        return 0
    raw = getattr(status, "value", status)
    return int(ctypes.c_int32(int(raw)).value)


__all__ = [
    "TLPM_DEFAULT_CHANNEL",
    "TlpmxPowerMeterClient",
]
