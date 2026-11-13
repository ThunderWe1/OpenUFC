from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from laser_platform.library import PAYLOAD_OFFSET, SCALAR_RECORD_DTYPE
from laser_platform.stats import elapsed_duration_s, estimated_sample_rate
from laser_platform.ufc.allan import AllanResult, non_overlapping_adev


class ScalarDiskAdevWorker:
    def __init__(
        self,
        library_file: Path,
        default_sample_rate_hz: float,
        out_queue: queue.Queue[object],
        result_factory: Callable[[AllanResult, int, float], object],
        error_factory: Callable[[Exception], object],
        thread_name: str,
    ) -> None:
        self.library_file = Path(library_file)
        self.default_sample_rate_hz = float(default_sample_rate_hz)
        self.out_queue = out_queue
        self.result_factory = result_factory
        self.error_factory = error_factory
        self.stop_event = threading.Event()
        self.final_requested = threading.Event()
        self.thread = threading.Thread(target=self._run, name=thread_name, daemon=True)
        self._last_sample_count = 0

    def start(self) -> None:
        self.thread.start()

    def request_final_update(self) -> None:
        self.final_requested.set()
        self.stop_event.set()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        next_update = time.monotonic()
        while True:
            now = time.monotonic()
            if self.final_requested.is_set():
                self._calculate_once(force=True)
                return
            if now >= next_update:
                _, elapsed_s = self._calculate_once(force=False)
                next_update = time.monotonic() + self._update_interval_s(elapsed_s)
            else:
                self.stop_event.wait(min(0.25, max(0.0, next_update - now)))
                if self.stop_event.is_set() and not self.final_requested.is_set():
                    return

    def _calculate_once(self, *, force: bool) -> tuple[int, float]:
        try:
            sample_count = self._sample_count()
            if sample_count < 4:
                return sample_count, 0.0
            if not force and sample_count == self._last_sample_count:
                return sample_count, self._elapsed_s(sample_count)

            data = np.memmap(
                self.library_file,
                dtype=SCALAR_RECORD_DTYPE,
                mode="r",
                offset=PAYLOAD_OFFSET,
                shape=(sample_count, 2),
            )
            elapsed = np.asarray(data[:, 0], dtype=np.float64)
            values = np.asarray(data[:, 1], dtype=np.float64)
            del data
            elapsed_s = elapsed_duration_s(elapsed)
            sample_rate_hz = estimated_sample_rate(
                elapsed,
                default_hz=self.default_sample_rate_hz,
            )
            result = non_overlapping_adev(values, sample_rate_hz=sample_rate_hz)
            self._last_sample_count = sample_count
            self.out_queue.put(self.result_factory(result, sample_count, elapsed_s))
            return sample_count, elapsed_s
        except Exception as exc:
            self.out_queue.put(self.error_factory(exc))
            return self._last_sample_count, self._elapsed_s(self._last_sample_count)

    def _sample_count(self) -> int:
        if not self.library_file.exists():
            return 0
        record_size = SCALAR_RECORD_DTYPE.itemsize * 2
        return max(0, self.library_file.stat().st_size - PAYLOAD_OFFSET) // record_size

    def _elapsed_s(self, sample_count: int) -> float:
        if sample_count < 2 or not self.library_file.exists():
            return 0.0
        data = np.memmap(
            self.library_file,
            dtype=SCALAR_RECORD_DTYPE,
            mode="r",
            offset=PAYLOAD_OFFSET,
            shape=(sample_count, 2),
        )
        elapsed_s = max(0.0, float(data[-1, 0] - data[0, 0]))
        del data
        return elapsed_s

    @staticmethod
    def _update_interval_s(elapsed_s: float) -> float:
        if elapsed_s < 600.0:
            return 5.0
        if elapsed_s < 3600.0:
            return 30.0
        return 120.0


__all__ = ["ScalarDiskAdevWorker"]
