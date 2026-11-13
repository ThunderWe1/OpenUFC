"""53220A/53230A instrument acquisition backend."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from collections.abc import Iterator

import numpy as np
import pyvisa

from laser_platform.visa_transport import configure_visa_termination


EXPECTED_FREQUENCY_HZ_BY_CHANNEL = {
    1: 10_000_000.0,
    2: 10_000_000.0,
    3: 100_000_000.0,
}

STOP_DRAIN_TIMEOUT_S = 30.0
STOP_DRAIN_BATCH_SIZE = 10_000


def list_visa_resources() -> tuple[str, ...]:
    """Return USB and LAN VISA resources visible to PyVISA."""

    return tuple(resource for resource in pyvisa.ResourceManager().list_resources()
                 if resource.startswith(("USB", "TCPIP")))


@dataclass(frozen=True)
class CounterConfig:
    resource: str
    channel: int = 1
    sample_rate_hz: float = 1000.0
    sample_count: int = 1_000_000
    timeout_ms: int = 10_000

    @property
    def expected_frequency_hz(self) -> float:
        try:
            return EXPECTED_FREQUENCY_HZ_BY_CHANNEL[int(self.channel)]
        except KeyError as exc:
            raise ValueError("channel must be 1, 2, or 3") from exc

    @property
    def chunk_size(self) -> int:
        return int(self.sample_rate_hz)

    @property
    def gate_time_s(self) -> float:
        return 1.0 / float(self.sample_rate_hz)


class Keysight53230A:
    """PyVISA controller for 53220A/53230A frequency acquisition."""

    def __init__(self) -> None:
        self._inst = None
        self._config: CounterConfig | None = None
        self.stop_drain_discarded_samples = 0

    def connect(self) -> str:
        if self._config is None:
            raise RuntimeError("configure must be called before connect")

        self._inst = pyvisa.ResourceManager().open_resource(self._config.resource)
        try:
            self._inst.timeout = self._config.timeout_ms
            configure_visa_termination(self._inst)
        except Exception:
            self.close()
            raise
        try:
            return str(self._inst.query("*IDN?")).strip()
        except Exception:
            return self._config.resource

    def configure(self, config: CounterConfig) -> None:
        self._config = config
        if self._inst is None:
            return

        ch = int(config.channel)
        expected = float(config.expected_frequency_hz)
        gate = float(config.gate_time_s)
        sample_count = int(config.sample_count)

        self._inst.write("*CLS")
        self._inst.write(f"CONF:FREQ {expected},DEF,(@{ch})")
        self._inst.write("FORM:DATA REAL,64")
        try:
            self._inst.write("FORM:BORD NORM")
        except Exception:
            pass
        self._inst.write("TRIG:SOUR IMM")
        self._inst.write("TRIG:COUN 1")
        self._inst.write(f"SAMP:COUN {sample_count}")
        self._inst.write("SENS:FREQ:MODE CONT")
        self._inst.write("SENS:FREQ:GATE:SOUR TIME")
        self._inst.write(f"SENS:FREQ:GATE:TIME {gate:.12g}")

    def start(self) -> None:
        if self._inst is None:
            raise RuntimeError("instrument is not connected")
        self._inst.write("INIT")

    def read_chunk(self, chunk_size: int) -> np.ndarray:
        if self._inst is None:
            raise RuntimeError("instrument is not connected")
        values = self._inst.query_binary_values(
            f"R? {int(chunk_size)}",
            datatype="d",
            is_big_endian=True,
            container=np.asarray,
            header_fmt="ieee",
        )
        return np.asarray(values, dtype=np.float64)

    def is_measuring(self) -> bool:
        if self._inst is None:
            raise RuntimeError("instrument is not connected")
        return bool(int(self._inst.query("STAT:OPER:COND?").strip()) & 16)

    def stop_and_drain(self) -> Iterator[np.ndarray]:
        """Save the pre-abort reading count, then empty memory without re-arming.

        The 53220A/53230A reference documents ABORt as returning to idle;
        INIT/READ/MEASure and configuration changes clear reading memory.
        DATA:POINts? avoids R?'s no-data error after the buffer is empty.
        Call only on the acquisition thread, after any pending read finishes.
        """
        if self._inst is None or self._config is None:
            raise RuntimeError("instrument is not connected")
        resource = self._inst
        self.stop_drain_discarded_samples = 0
        original_timeout = resource.timeout
        deadline = time.monotonic() + STOP_DRAIN_TIMEOUT_S

        def limit_timeout() -> None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out while stopping and draining the counter")
            resource.timeout = max(1, min(self._config.timeout_ms, math.ceil(remaining * 1000)))

        try:
            limit_timeout()
            # ABOR can append an invalid final reading; freeze the completed prefix first.
            remaining_to_save = int(resource.query("DATA:POIN?").strip())
            if not 0 <= remaining_to_save <= 1_000_000:
                raise RuntimeError(f"Invalid counter buffer count: {remaining_to_save}")
            limit_timeout()
            # Unlike the best-effort cleanup abort(), failures must be reported.
            resource.write("ABOR")
            limit_timeout()
            if resource.query("*OPC?").strip() not in ("1", "+1"):
                raise RuntimeError("Counter did not confirm completion of the stop command")
            expected_remaining = None
            while True:
                limit_timeout()
                available = int(resource.query("DATA:POIN?").strip())
                if not 0 <= available <= 1_000_000:
                    raise RuntimeError(f"Invalid counter buffer count: {available}")
                if expected_remaining is not None and available != expected_remaining:
                    raise RuntimeError("Counter buffer changed unexpectedly after stopping")
                if available < remaining_to_save:
                    raise RuntimeError("Counter lost readings that were buffered before stopping")
                if available == 0:
                    return
                to_read = min(available, STOP_DRAIN_BATCH_SIZE)
                limit_timeout()
                values = self.read_chunk(to_read)
                if not 0 < values.size <= to_read:
                    raise RuntimeError("Counter returned an unexpected number of buffered readings")
                expected_remaining = available - int(values.size)
                to_save = min(remaining_to_save, int(values.size))
                remaining_to_save -= to_save
                self.stop_drain_discarded_samples += int(values.size) - to_save
                if to_save:
                    yield values[:to_save]
        finally:
            resource.timeout = original_timeout

    def recover_after_error(self) -> None:
        if self._inst is None:
            return
        try:
            self._inst.clear()
        except Exception:
            pass
        try:
            self._inst.write("*CLS")
        except Exception:
            pass

    def abort(self) -> None:
        if self._inst is None:
            return
        try:
            self._inst.write("ABOR")
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._inst is not None:
                self._inst.close()
        finally:
            self._inst = None


