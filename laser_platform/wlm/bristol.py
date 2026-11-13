from __future__ import annotations

import math
import time
from typing import Any, Callable

from laser_platform.wlm.client import WavelengthMeterError
from laser_platform.wlm.models import (
    WLM_OPERATION_TIMEOUT_S,
    WavelengthMeterConfig,
    WavelengthMeterIdentity,
    split_wlm_resource,
)


IDENTITY_QUERY = "*IDN?"
WAVELENGTH_QUERY = ":READ:WAV?"
WAVELENGTH_QUERY_771 = ":READ:SCAL:WAV?"
COMMAND_TERMINATOR = "\r\n"
_BANNER_DRAIN_TIMEOUT_S = 3.0
_BANNER_QUIET_TIMEOUT_S = 0.5
_MAX_RESPONSE_LINES = 32

TelnetConnectionFactory = Callable[[str, int, float], Any]


class BristolWavelengthMeterClient:
    """Blocking Telnet adapter for the Bristol wavelength-meter SCPI subset."""

    def __init__(
        self,
        connection_factory: TelnetConnectionFactory | None = None,
    ) -> None:
        self._connection_factory = connection_factory or _default_connection_factory
        self._connection: Any | None = None
        self._identity: WavelengthMeterIdentity | None = None
        self._resource_name: str | None = None

    @property
    def identity(self) -> WavelengthMeterIdentity | None:
        return self._identity

    @property
    def resource_name(self) -> str | None:
        return self._resource_name

    def connect(self, config: WavelengthMeterConfig) -> WavelengthMeterIdentity:
        config.validate()
        self.close()

        host, port = split_wlm_resource(config.resource)
        connection: Any | None = None
        try:
            connection = self._connection_factory(host, port, WLM_OPERATION_TIMEOUT_S)
            self._connection = connection
            connection.connect()
            _drain_banner(connection)
            try:
                identity_text = _query_line(
                    connection,
                    IDENTITY_QUERY,
                    timeout_s=WLM_OPERATION_TIMEOUT_S,
                )
            except TimeoutError:
                identity_text = ""

            identity = _parse_identity(identity_text, config.canonical_resource)
            self._identity = identity
            self._resource_name = config.resource
            return identity
        except Exception as exc:
            self._clear_connection()
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            if isinstance(exc, WavelengthMeterError):
                raise
            raise WavelengthMeterError(
                f"Could not connect to Bristol wavelength meter at "
                f"{config.canonical_resource}: {exc}"
            ) from exc

    def read_once(self) -> float:
        connection = self._connection
        if connection is None:
            raise WavelengthMeterError("Wavelength meter is not connected.")
        command = _wavelength_query_for_identity(self._identity)
        try:
            response = _query_line(
                connection,
                command,
                timeout_s=WLM_OPERATION_TIMEOUT_S,
            )
        except WavelengthMeterError:
            raise
        except Exception as exc:
            raise WavelengthMeterError(f"Wavelength query failed: {exc}") from exc

        try:
            wavelength_nm = float(response)
        except (TypeError, ValueError) as exc:
            raise WavelengthMeterError(
                f"Bristol wavelength meter returned a malformed wavelength: {response!r}."
            ) from exc
        if not math.isfinite(wavelength_nm):
            raise WavelengthMeterError(
                "Bristol wavelength meter returned a non-finite wavelength."
            )
        if wavelength_nm <= 0:
            raise WavelengthMeterError(
                "Bristol wavelength meter returned a non-positive wavelength."
            )
        return wavelength_nm

    def close(self) -> None:
        connection = self._connection
        self._clear_connection()
        if connection is None:
            return
        try:
            connection.close()
        except Exception as exc:
            raise WavelengthMeterError(f"Could not close wavelength meter connection: {exc}") from exc

    def _clear_connection(self) -> None:
        self._connection = None
        self._identity = None
        self._resource_name = None


def _default_connection_factory(host: str, port: int, timeout_s: float) -> Any:
    # Keep telnetlib3 optional until a real Bristol connection is requested.
    try:
        from telnetlib3.sync import TelnetConnection
    except ImportError as exc:
        raise WavelengthMeterError(
            "Bristol wavelength meter support requires the telnetlib3 package."
        ) from exc
    return TelnetConnection(
        host,
        port,
        timeout=timeout_s,
        connect_timeout=timeout_s,
        encoding="utf8",
    )


def _drain_banner(connection: Any) -> None:
    """Consume any connection-time banner until the socket is briefly quiet."""

    deadline = time.monotonic() + _BANNER_DRAIN_TIMEOUT_S
    received = ""
    for _ in range(_MAX_RESPONSE_LINES):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            chunk = connection.read_some(
                timeout=min(_BANNER_QUIET_TIMEOUT_S, remaining)
            )
        except TimeoutError:
            return
        text = _coerce_chunk(chunk)
        if not text:
            return
        received += text
        if "\r\n\r\n" in received or "\n\n" in received:
            return
    raise WavelengthMeterError("Bristol wavelength meter banner did not terminate.")


def _query_line(connection: Any, command: str, *, timeout_s: float) -> str:
    connection.write(command + COMMAND_TERMINATOR)
    connection.flush()

    deadline = time.monotonic() + timeout_s
    skipped_status_line = False
    for _ in range(_MAX_RESPONSE_LINES):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for {command} response.")
        line = connection.readline(timeout=remaining)
        text = _coerce_text(line)
        if not text:
            continue
        if text == "1" and not skipped_status_line:
            skipped_status_line = True
            continue
        return text
    raise TimeoutError(
        f"Bristol wavelength meter returned no response for {command}."
    )


def _coerce_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value or "").strip()


def _coerce_chunk(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _parse_identity(response: str, canonical_endpoint: str) -> WavelengthMeterIdentity:
    raw = str(response or "").strip()
    if not raw:
        fallback_raw = f"Bristol Wavelength Meter @ {canonical_endpoint}"
        return WavelengthMeterIdentity(
            manufacturer="Bristol Instruments",
            model="Wavelength Meter",
            serial="",
            firmware="",
            raw=fallback_raw,
        )

    fields = [part.strip() for part in raw.split(",")]
    fields.extend([""] * max(0, 4 - len(fields)))
    return WavelengthMeterIdentity(
        manufacturer=fields[0],
        model=fields[1],
        serial=fields[2],
        firmware=fields[3],
        raw=raw,
    )


def _wavelength_query_for_identity(
    identity: WavelengthMeterIdentity | None,
) -> str:
    model = identity.model.strip().casefold() if identity is not None else ""
    if model.startswith("771"):
        return WAVELENGTH_QUERY_771
    return WAVELENGTH_QUERY


__all__ = [
    "BristolWavelengthMeterClient",
    "COMMAND_TERMINATOR",
    "IDENTITY_QUERY",
    "TelnetConnectionFactory",
    "WAVELENGTH_QUERY",
    "WAVELENGTH_QUERY_771",
]
