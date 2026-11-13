"""Bounded disk queue: counter I/O never waits for routine file flushes."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

import numpy as np

from laser_platform.library import LmpWriter


class FrequencyRecorder:
    def __init__(self, storage: LmpWriter, on_data: Callable, queue_size: int = 32) -> None:
        self.storage = storage
        self.on_data = on_data
        self.pending: queue.Queue = queue.Queue(maxsize=queue_size)
        self.finished = threading.Event()
        self.error: Exception | None = None
        self._lock = threading.Lock()
        self._sample_count = 0
        self._segment_starts: tuple[int, ...] = (0,)
        self._closing = False
        self.thread = threading.Thread(target=self._run, name="frequency-writer", daemon=True)
        self.thread.start()

    def snapshot(self) -> tuple[int, tuple[int, ...]]:
        with self._lock:
            return self._sample_count, self._segment_starts

    def check(self) -> None:
        if self.error is not None:
            raise RuntimeError(f"Frequency recording failed: {self.error}") from self.error

    def _put(self, item) -> None:
        while True:
            self.check()
            if self.finished.is_set():
                raise RuntimeError("Frequency recording is already closed")
            try:
                self.pending.put(item, timeout=0.1)
                return
            except queue.Full:
                # Apply backpressure rather than dropping acquired readings.
                continue

    def submit(self, values: np.ndarray, elapsed_s: float, segment_start: bool = False) -> None:
        if self._closing:
            raise RuntimeError("Frequency recording is closing")
        self._put((np.array(values, dtype=np.float64, copy=True), elapsed_s, segment_start))

    def finish(self, metadata: dict | None = None) -> None:
        try:
            if not self._closing and not self.finished.is_set():
                self._closing = True
                self._put(metadata or {})
        finally:
            self.thread.join()
        self.check()

    def _run(self) -> None:
        try:
            while True:
                item = self.pending.get()
                if isinstance(item, dict):
                    self.storage.metadata.update(item)
                    break
                values, elapsed_s, segment_start = item
                if segment_start and values.size:
                    self.storage.mark_ufc_segment_start()
                self.storage.append_ufc_frequency(values)
                with self._lock:
                    self._sample_count = self.storage.sample_count
                    self._segment_starts = tuple(self.storage.metadata["ufc_segment_starts"])
                self.on_data(values, self._sample_count, elapsed_s, segment_start)
        except Exception as exc:
            self.error = exc
            self.storage.metadata["recording_error"] = str(exc)
        finally:
            try:
                self.storage.close()
            except Exception as exc:
                if self.error is None:
                    self.error = exc
            self.finished.set()
