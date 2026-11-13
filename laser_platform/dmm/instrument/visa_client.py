from __future__ import annotations

from typing import Any

import numpy as np
import pyvisa

from laser_platform.dmm.instrument.base import InstrumentError, InstrumentIdentity
from laser_platform.visa_transport import configure_visa_termination
from laser_platform.dmm.models import (
    SUPPORTED_DMM_MODELS,
    DMM_OPERATION_TIMEOUT_MS,
    DmmModelProfile,
    MeasurementConfig,
    dmm_model_profile,
    normalize_dmm_model,
)


class DmmBatchConfigurationError(InstrumentError):
    """Raised when the connected DMM rejects timed batch configuration."""


class DmmBatchReadError(InstrumentError):
    """Raised when a DMM batch response cannot be decoded safely."""


class VisaInstrumentClient:
    def __init__(self) -> None:
        self._manager = None
        self._resource = None
        self._identity: InstrumentIdentity | None = None
        self._profile: DmmModelProfile | None = None
        self._resource_name: str | None = None

    @property
    def identity(self) -> InstrumentIdentity | None:
        return self._identity

    @property
    def resource_name(self) -> str | None:
        return self._resource_name

    def discover_resources(self) -> list[str]:
        manager = self._resource_manager()
        try:
            resources = manager.list_resources()
        except Exception as exc:  # pragma: no cover - depends on VISA runtime
            raise InstrumentError(f"Unable to enumerate VISA resources: {exc}") from exc
        return sorted(
            [
                resource
                for resource in resources
                if resource.startswith(("USB", "TCPIP"))
            ]
        )

    def connect(self, target: str) -> InstrumentIdentity:
        target = target.strip()
        if not target:
            raise ValueError("DMM VISA resource cannot be empty.")
        manager = self._resource_manager()
        self.close()
        resource = None
        try:
            resource = manager.open_resource(target)
            resource.timeout = DMM_OPERATION_TIMEOUT_MS
            configure_visa_termination(resource)
            identity = self._parse_identity(resource.query("*IDN?").strip())
        except Exception as exc:
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
            raise InstrumentError(f"Unable to connect to {target}: {exc}") from exc
        profile = dmm_model_profile(identity.model)
        if profile is None:
            try:
                resource.close()
            except Exception:
                pass
            supported = ", ".join(SUPPORTED_DMM_MODELS)
            raise InstrumentError(
                f"Connected instrument is {identity.raw!r}. Supported DMM models are: {supported}."
            )
        self._resource = resource
        self._resource_name = target
        self._identity = identity
        self._profile = profile
        return identity

    def configure(self, config: MeasurementConfig, *, batch_size: int) -> None:
        config.validate()
        if int(batch_size) <= 0:
            raise ValueError("DMM batch_size must be greater than zero.")
        resource = self._require_resource()
        profile = self._require_profile()
        try:
            profile.validate_measurement(config)
        except ValueError as exc:
            raise InstrumentError(str(exc)) from exc
        prefix = config.function.value
        try:
            resource.write("*CLS")
            use_10a_terminal = (
                not config.autorange
                and config.function.is_current
                and profile.supports_10a_terminal
                and config.range_value is not None
                and abs(config.range_value - 10.0) < 1e-12
            )
            if use_10a_terminal:
                # TERMinals 10 forces the 10 A range. RANGe only addresses
                # the 3 A path, so no separate RANGe command is valid here.
                resource.write(f"CONF:{prefix}")
                resource.write(f"{prefix}:TERM 10")
            elif config.autorange:
                resource.write(f"CONF:{prefix} AUTO")
            else:
                resource.write(f"CONF:{prefix} {config.range_value}")
            if config.function.supports_nplc:
                resource.write(f"{prefix}:NPLC {config.nplc}")
            resource.write("TRIG:SOUR IMM")
            resource.write("TRIG:COUN INF")
            resource.write(f"SAMP:COUN {int(batch_size)}")
            resource.write("SAMP:SOUR TIM")
            resource.write(f"SAMP:TIM {config.interval_ms / 1000.0:g}")
            if profile.supports_ascii_format:
                resource.write("FORM:DATA ASC")
            else:
                resource.write("FORM:DATA REAL,64")
            try:
                self._raise_for_system_error(resource, profile.model)
            except InstrumentError as exc:
                raise DmmBatchConfigurationError(str(exc)) from exc
        except InstrumentError:
            raise
        except Exception as exc:
            raise DmmBatchConfigurationError(f"Failed to configure timed batch sampling: {exc}") from exc

    def stop(self) -> None:
        if self._resource is None:
            return
        try:
            self._resource.write("ABOR")
        except Exception:
            return

    def start_sampling(self) -> None:
        resource = self._require_resource()
        try:
            resource.write("INIT")
        except Exception as exc:
            raise DmmBatchConfigurationError(f"Failed to start DMM sampling: {exc}") from exc

    def read_batch(self, max_readings: int) -> np.ndarray:
        if int(max_readings) <= 0:
            raise ValueError("DMM max_readings must be greater than zero.")
        resource = self._require_resource()
        profile = self._require_profile()
        command = f"R? {int(max_readings)}"
        try:
            if profile.supports_ascii_format:
                values = resource.query_ascii_values(command, container=np.array)
            else:
                values = resource.query_binary_values(
                    command,
                    datatype="d",
                    is_big_endian=True,
                    container=np.array,
                )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise DmmBatchReadError(f"DMM batch response could not be decoded: {exc}") from exc
        except Exception as exc:
            raise InstrumentError(f"DMM batch read failed: {exc}") from exc
        try:
            data = np.asarray(values, dtype=np.float64).reshape(-1)
        except Exception as exc:
            raise DmmBatchReadError(f"DMM batch response could not be decoded: {exc}") from exc
        if not np.all(np.isfinite(data)):
            raise DmmBatchReadError("DMM batch read returned a non-finite value.")
        return data

    def points_available(self) -> int:
        resource = self._require_resource()
        try:
            count = int(str(resource.query("DATA:POIN?")).strip())
        except Exception as exc:
            raise InstrumentError(f"Could not read DMM pending sample count: {exc}") from exc
        if count < 0:
            raise InstrumentError(f"DMM returned an invalid pending sample count: {count}")
        return count

    def close(self) -> None:
        if self._resource is not None:
            try:
                self._resource.close()
            except Exception:
                pass
        self._resource = None
        self._identity = None
        self._profile = None
        self._resource_name = None

    def _resource_manager(self) -> Any:
        if self._manager is None:
            try:
                self._manager = pyvisa.ResourceManager()
            except Exception as exc:
                raise InstrumentError(f"Unable to load VISA runtime: {exc}") from exc
        return self._manager

    def _require_resource(self) -> Any:
        if self._resource is None:
            raise InstrumentError("Instrument is not connected.")
        return self._resource

    def _require_profile(self) -> DmmModelProfile:
        if self._profile is None:
            raise InstrumentError("Instrument model capabilities are unavailable.")
        return self._profile

    @staticmethod
    def _raise_for_system_error(resource: Any, model: str) -> None:
        try:
            response = str(resource.query("SYST:ERR?") or "").strip()
        except Exception as exc:
            raise InstrumentError(
                f"Configured {model}, but could not read its SCPI error queue: {exc}"
            ) from exc
        try:
            code = int(response.split(",", 1)[0].strip())
        except (TypeError, ValueError) as exc:
            raise InstrumentError(
                f"Configured {model}, but it returned a malformed SCPI error response: {response!r}."
            ) from exc
        if code != 0:
            raise InstrumentError(
                f"{model} rejected one or more configuration commands: {response}"
            )

    def _parse_identity(self, raw: str) -> InstrumentIdentity:
        parts = [part.strip() for part in raw.split(",")]
        while len(parts) < 4:
            parts.append("")
        manufacturer, model, serial, firmware = parts[:4]
        model = normalize_dmm_model(model)
        return InstrumentIdentity(
            manufacturer=manufacturer,
            model=model,
            serial=serial,
            firmware=firmware,
            raw=raw,
        )
