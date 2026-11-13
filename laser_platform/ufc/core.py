from __future__ import annotations

import queue
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable

import numpy as np

from laser_platform.controller import AcquisitionController
from laser_platform.library import LmpWriter, PAYLOAD_OFFSET, UFC_SAMPLE_DTYPE
from laser_platform.ufc.allan import AllanResult, frequency_file_adev
from laser_platform.ufc.instrument import CounterConfig, Keysight53230A
from laser_platform.ufc.recording import FrequencyRecorder


@dataclass(frozen=True)
class AppConfig:
    resource: str
    channel: int
    sample_rate_hz: float
    optical_frequency_hz: float
    divide_adev_by_optical_frequency: bool
    divide_adev_by_sqrt2: bool
    library_dir: Path
    display_name: str
    instrument_instance_id: str = ""


@dataclass(frozen=True)
class DataMessage:
    frequency_hz: np.ndarray
    total_samples: int
    elapsed_s: float
    library_file: Path
    segment_start: bool = False


@dataclass(frozen=True)
class AdevMessage:
    adev: AllanResult
    sample_count: int
    elapsed_s: float


@dataclass(frozen=True)
class StatusMessage:
    text: str
    severity: str = "info"


@dataclass(frozen=True)
class DoneMessage:
    text: str
    library_file: Path | None
    severity: str = "info"


@dataclass(frozen=True)
class ErrorMessage:
    text: str
    details: str


@dataclass(frozen=True)
class RecoverableAcquisitionErrorMessage:
    operation: str
    total_errors: int
    consecutive_errors: int
    message: str


class DiskAdevWorker:
    """Background ADEV calculator that reads the current library file from disk."""

    def __init__(
        self,
        library_file: Path,
        sample_rate_hz: float,
        optical_frequency_hz: float,
        divide_by_optical_frequency: bool,
        divide_by_sqrt2: bool,
        out_queue: queue.Queue[object],
        recording_snapshot: Callable[[], tuple[int, tuple[int, ...]]],
    ) -> None:
        self.library_file = Path(library_file)
        self.sample_rate_hz = float(sample_rate_hz)
        self.optical_frequency_hz = float(optical_frequency_hz)
        self.divide_by_optical_frequency = bool(divide_by_optical_frequency)
        self.divide_by_sqrt2 = bool(divide_by_sqrt2)
        self.out_queue = out_queue
        self.recording_snapshot = recording_snapshot
        self.stop_event = threading.Event()
        self.final_requested = threading.Event()
        self.thread = threading.Thread(target=self._run, name="disk-adev-worker", daemon=True)
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
                sample_count = self._calculate_once(force=False)
                elapsed_s = sample_count / self.sample_rate_hz if sample_count else 0.0
                next_update = time.monotonic() + self._update_interval_s(elapsed_s)
            else:
                self.stop_event.wait(min(0.25, max(0.0, next_update - now)))
                if self.stop_event.is_set() and not self.final_requested.is_set():
                    return

    def _calculate_once(self, force: bool) -> int:
        try:
            sample_count, segment_starts = self.recording_snapshot()
            if sample_count < 4:
                return sample_count
            if not force and sample_count == self._last_sample_count:
                return sample_count

            result = frequency_file_adev(
                self.library_file,
                sample_count=sample_count,
                sample_rate_hz=self.sample_rate_hz,
                optical_frequency_hz=self.optical_frequency_hz,
                dtype=UFC_SAMPLE_DTYPE,
                offset=PAYLOAD_OFFSET,
                divide_by_optical_frequency=self.divide_by_optical_frequency,
                divide_by_sqrt2=self.divide_by_sqrt2,
                segment_starts=segment_starts,
            )
            self._last_sample_count = sample_count
            self.out_queue.put(
                AdevMessage(
                    adev=result,
                    sample_count=sample_count,
                    elapsed_s=sample_count / self.sample_rate_hz,
                )
            )
            return sample_count
        except Exception as exc:
            self.out_queue.put(StatusMessage(f"ADEV update failed: {exc}", "warning"))
            return self._last_sample_count

    @staticmethod
    def _update_interval_s(elapsed_s: float) -> float:
        if elapsed_s < 600.0:
            return 5.0
        if elapsed_s < 3600.0:
            return 30.0
        return 120.0


class AcquisitionWorker:
    def __init__(self, config: AppConfig, out_queue: queue.Queue[object]) -> None:
        self.config = config
        self.out_queue = out_queue
        self.stop_event = threading.Event()
        self.recording_finalized = threading.Event()
        self.thread = threading.Thread(target=self._run, name="acquisition-worker", daemon=True)
        self.library_file: Path | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        # Never send SCPI from the caller while the worker is reading a reply.
        # The worker finishes its bounded read, then stops and drains serially.
        self.stop_event.set()

    def _run(self) -> None:
        source = Keysight53230A()
        storage: LmpWriter | None = None
        recorder: FrequencyRecorder | None = None
        adev_worker: DiskAdevWorker | None = None
        library_file: Path | None = None
        acquisition_started = False
        stop_read_error: Exception | None = None
        failure_message: ErrorMessage | None = None
        started = time.monotonic()
        try:
            if self.stop_event.is_set():
                self.out_queue.put(DoneMessage("Stopped before acquisition started", None))
                return
            counter_config = CounterConfig(
                resource=self.config.resource,
                channel=self.config.channel,
                sample_rate_hz=self.config.sample_rate_hz,
            )
            source.configure(counter_config)
            instrument_id = source.connect()
            source.configure(counter_config)

            settings = {
                "sample_rate_hz": self.config.sample_rate_hz,
                "optical_frequency_hz": self.config.optical_frequency_hz,
                "divide_adev_by_optical_frequency": self.config.divide_adev_by_optical_frequency,
                "divide_adev_by_sqrt2": self.config.divide_adev_by_sqrt2,
                "expected_frequency_hz": counter_config.expected_frequency_hz,
                "channel": self.config.channel,
                "chunk_size": counter_config.chunk_size,
            }
            storage = LmpWriter(
                library_dir=self.config.library_dir,
                app_type="ufc",
                abbreviation="ufc",
                display_name=self.config.display_name,
                instrument_id=instrument_id,
                resource=self.config.resource,
                unit="Hz",
                sample_layout={
                    "kind": "ufc_frequency_f64",
                    "record_size": int(UFC_SAMPLE_DTYPE.itemsize),
                    "dtype": "<f8",
                    "adev_semantic": "adev",
                    "fields": [{"name": "frequency_hz", "unit": "Hz"}],
                },
                settings=settings,
                instrument_instance_id=self.config.instrument_instance_id,
            )
            library_file = storage.path
            self.library_file = library_file
            self.out_queue.put(StatusMessage(f"Connected: {instrument_id}"))

            recorder = FrequencyRecorder(storage, lambda values, count, elapsed, boundary:
                self.out_queue.put(DataMessage(values, count, elapsed, library_file, boundary)))

            if not self.stop_event.is_set():
                source.start()
                acquisition_started = True
            segment_started = time.monotonic()
            adev_worker = DiskAdevWorker(
                library_file=storage.path,
                sample_rate_hz=self.config.sample_rate_hz,
                optical_frequency_hz=self.config.optical_frequency_hz,
                divide_by_optical_frequency=self.config.divide_adev_by_optical_frequency,
                divide_by_sqrt2=self.config.divide_adev_by_sqrt2,
                out_queue=self.out_queue,
                recording_snapshot=recorder.snapshot,
            )
            adev_worker.start()
            self.out_queue.put(StatusMessage("Acquisition running"))
            segment_samples = 0
            read_interval_s = max(0.01, float(counter_config.chunk_size) / float(counter_config.sample_rate_hz))
            next_read_time = segment_started + read_interval_s
            rearm_count = 0
            total_recoverable_errors = 0
            consecutive_errors = 0
            last_error_status = 0.0

            pending_segment_start = True
            recovery_required = False
            received_samples = 0

            def save(values: np.ndarray) -> None:
                nonlocal pending_segment_start, received_samples
                if values.size:
                    recorder.submit(values, time.monotonic() - started, pending_segment_start)
                    received_samples += int(values.size)
                    pending_segment_start = False

            while not self.stop_event.is_set():
                recorder.check()
                if recovery_required or segment_samples >= counter_config.sample_count:
                    # INIT clears reading memory. Normal completion is known only
                    # after every requested sample has been retrieved. On recovery,
                    # explicitly stop/drain before any configuration clears memory.
                    if recovery_required:
                        for values in source.stop_and_drain():
                            save(values)
                    if self.stop_event.is_set():
                        break
                    rearm_count += 1
                    segment_started = self._restart_segment(
                        source, counter_config, rearm_count,
                        "read recovery" if recovery_required else f"{segment_samples:,} readings",
                        reconfigure=recovery_required,
                    )
                    segment_samples = 0
                    pending_segment_start = True
                    recovery_required = False
                    next_read_time = segment_started + read_interval_s

                to_read = min(counter_config.chunk_size, counter_config.sample_count - segment_samples)
                wait_s = next_read_time - time.monotonic()
                if wait_s > 0 and self.stop_event.wait(wait_s):
                    break
                if self.stop_event.is_set():
                    break

                read_started = time.monotonic()
                try:
                    values = source.read_chunk(to_read)
                    if values.size > to_read:
                        raise RuntimeError("Counter returned more readings than requested")
                except Exception as exc:
                    # A destructive R? failure may lose samples. Never treat the
                    # next returned batch as contiguous with the preceding one.
                    pending_segment_start = True
                    if self.stop_event.is_set():
                        stop_read_error = exc
                        break
                    total_recoverable_errors += 1
                    consecutive_errors += 1
                    last_error_status = self._report_recoverable_error(
                        "read", exc, total_recoverable_errors,
                        consecutive_errors, last_error_status,
                    )
                    self._recover_source(source)
                    recovery_required = self._segment_should_force_rearm(
                        counter_config, segment_samples, segment_started)
                    self._sleep_after_error(consecutive_errors)
                    next_read_time = time.monotonic() + min(0.25, read_interval_s / 4.0)
                    continue
                if values.size == 0:
                    recovery_required = self._segment_should_force_rearm(
                        counter_config, segment_samples, segment_started) and not source.is_measuring()
                    next_read_time = time.monotonic() + min(0.25, read_interval_s / 4.0)
                    continue

                if consecutive_errors:
                    self.out_queue.put(StatusMessage(f"Acquisition recovered after {consecutive_errors} transient error(s)"))
                consecutive_errors = 0
                save(values)
                segment_samples += int(values.size)
                next_size = min(counter_config.chunk_size, counter_config.sample_count - segment_samples)
                # Schedule against acquired sample count, not the end of a transfer.
                # Lagging reads catch up without accumulating one transfer delay
                # per batch; short/empty replies still cannot cause a busy loop.
                next_read_time = max(
                    segment_started + (segment_samples + next_size) / counter_config.sample_rate_hz,
                    read_started + 0.01,
                )

            self.out_queue.put(StatusMessage("Stopping acquisition and saving buffered readings"))
            done_text = "Stopped cleanly"
            done_severity = "info"
            final_metadata = {}
            if acquisition_started:
                saved_before_drain = received_samples
                drain_error = None
                try:
                    if stop_read_error is not None:
                        # A failed destructive R? may have consumed readings or
                        # left a partial reply. Do not issue queries on that
                        # uncertain response stream or claim a complete drain.
                        raise RuntimeError(f"The final in-flight read failed: {stop_read_error}")
                    for values in source.stop_and_drain():
                        save(values)
                except Exception as exc:
                    drain_error = str(exc)
                    done_text = "Stopped; counter stop/buffer recovery could not be fully confirmed"
                    done_severity = "warning"
                    self.out_queue.put(StatusMessage(f"{done_text}: {exc}", "warning"))
                    source.abort()
                final_metadata["stop_drain"] = {
                    "complete": drain_error is None,
                    "saved_samples": received_samples - saved_before_drain,
                    "discarded_after_stop": source.stop_drain_discarded_samples if stop_read_error is None else 0,
                    "error": drain_error,
                }
            recorder.finish(final_metadata)
            # Backend shutdown must keep the process alive through the drain
            # and file flush; it need not wait for the final display-only ADEV.
            self.recording_finalized.set()
            if adev_worker is not None:
                self.out_queue.put(StatusMessage("Final ADEV update from full file"))
                adev_worker.request_final_update()
                adev_worker.thread.join(timeout=300.0)
            self.out_queue.put(DoneMessage(done_text, library_file, done_severity))
        except Exception as exc:
            failure_message = ErrorMessage(str(exc), traceback.format_exc())
        finally:
            try:
                source.abort()
            except Exception:
                pass
            try:
                source.close()
            except Exception:
                pass
            try:
                if recorder is not None:
                    recorder.finish({"acquisition_error": failure_message.text} if failure_message else None)
                elif storage is not None:
                    storage.close()
            except Exception:
                pass
            self.recording_finalized.set()
            if adev_worker is not None and adev_worker.thread.is_alive():
                adev_worker.stop()
                adev_worker.thread.join(timeout=2.0)
            self.library_file = None
        if failure_message is not None:
            self.out_queue.put(failure_message)

    def _report_recoverable_error(
        self,
        operation: str,
        exc: Exception,
        total_errors: int,
        consecutive_errors: int,
        last_report_time: float,
    ) -> float:
        now = time.monotonic()
        if consecutive_errors == 1 or now - last_report_time >= 10.0:
            self.out_queue.put(
                RecoverableAcquisitionErrorMessage(
                    operation=operation,
                    total_errors=total_errors,
                    consecutive_errors=consecutive_errors,
                    message=str(exc),
                )
            )
            return now
        return last_report_time

    def _recover_source(self, source) -> None:
        try:
            source.recover_after_error()
        except Exception:
            pass

    def _restart_segment(self, source, config: CounterConfig, rearm_count: int,
                         reason: str, *, reconfigure: bool = False) -> float:
        # The preceding segment has already been fully retrieved (or stopped
        # and drained for recovery). Only recovery needs configuration commands.
        if reconfigure:
            source.configure(config)
        source.start()
        started = time.monotonic()
        self.out_queue.put(StatusMessage(f"Re-armed counter after {reason}; boundary {rearm_count}"))
        return started

    def _segment_should_force_rearm(
        self,
        config: CounterConfig,
        segment_samples: int,
        segment_started: float,
    ) -> bool:
        segment_duration_s = float(config.sample_count) / float(config.sample_rate_hz)
        elapsed_s = time.monotonic() - segment_started
        past_time_boundary = elapsed_s >= segment_duration_s + max(2.0, 2.0 * float(config.chunk_size) / float(config.sample_rate_hz))
        return past_time_boundary

    def _sleep_after_error(self, consecutive_errors: int) -> None:
        delay_s = min(10.0, 0.25 * (2 ** min(consecutive_errors - 1, 6)))
        self.stop_event.wait(delay_s)


class BackendController(AcquisitionController):
    def __init__(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        super().__init__(
            event_from_message, (DoneMessage, ErrorMessage), "backend-dispatcher", on_event
        )

    def start_acquisition(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None:
                raise RuntimeError("acquisition is already running")
            config = config_from_payload(payload)
            worker = AcquisitionWorker(config, self.messages)
            self._worker = worker
        self.publish("status", {"text": "Connecting", "badge": "OFFLINE"})
        worker.start()
        return {"ok": True}

    def stop_acquisition(self) -> dict[str, Any]:
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.stop()
            self.publish("status", {"text": "Stop requested", "badge": "BUSY"})
        return {"ok": True}

    def shutdown(self) -> None:
        with self._lock:
            worker = self._worker
        self.stop_acquisition()
        if worker is not None:
            # Includes in-flight VISA I/O, the drain budget (30 s),
            # and headroom for transport and file finalization.
            worker.recording_finalized.wait(timeout=60.0)
        self._dispatcher_stop.set()
        self.messages.put(StatusMessage("Backend shutting down"))


def config_from_payload(payload: dict[str, Any]) -> AppConfig:
    sample_rate = float(payload.get("sample_rate_hz", 1000.0))
    if sample_rate not in (1, 10, 100, 1000, 5000, 10000, 50000):
        raise ValueError("sample_rate_hz must be 1, 10, 100, 1000, 5000, 10000, or 50000")
    channel = int(payload.get("channel", 1))
    if channel not in (1, 2, 3):
        raise ValueError("channel must be 1, 2, or 3")

    resource = str(payload.get("resource", "")).strip()
    if not resource:
        raise ValueError("select a VISA resource")

    return AppConfig(
        resource=resource,
        channel=channel,
        sample_rate_hz=sample_rate,
        optical_frequency_hz=float(payload.get("optical_frequency_hz", 3.52e14)),
        divide_adev_by_optical_frequency=bool(payload.get("divide_adev_by_optical_frequency", True)),
        divide_adev_by_sqrt2=bool(payload.get("divide_adev_by_sqrt2", True)),
        library_dir=Path(str(payload.get("library_dir", Path.cwd() / "runs"))).expanduser(),
        display_name=str(payload.get("display_name", "") or "").strip(),
        instrument_instance_id=str(payload.get("instrument_instance_id", "") or "").strip(),
    )


def event_from_message(msg: object) -> dict[str, Any] | None:
    if isinstance(msg, StatusMessage):
        normalized = msg.text.lower()
        if normalized.startswith("connected:"):
            badge = "READY"
        elif "shutting down" in normalized:
            badge = "OFFLINE"
        else:
            badge = "BUSY"
        return {"event": "status", "data": {"text": msg.text, "badge": badge, "severity": msg.severity}}
    if isinstance(msg, DataMessage):
        return {
            "event": "data",
            "data": {
                "frequency_hz": msg.frequency_hz.astype(float).tolist(),
                "total_samples": int(msg.total_samples),
                "elapsed_s": float(msg.elapsed_s),
                "library_file": str(msg.library_file),
                "segment_start": msg.segment_start,
            },
        }
    if isinstance(msg, AdevMessage):
        return {
            "event": "adev",
            "data": {
                "tau_s": msg.adev.tau_s.astype(float).tolist(),
                "adev": msg.adev.adev.astype(float).tolist(),
                "sample_count": int(msg.sample_count),
                "elapsed_s": float(msg.elapsed_s),
            },
        }
    if isinstance(msg, RecoverableAcquisitionErrorMessage):
        return {
            "event": "recoverable_error",
            "data": {
                "operation": msg.operation,
                "total_errors": int(msg.total_errors),
                "consecutive_errors": int(msg.consecutive_errors),
                "message": msg.message,
            },
        }
    if isinstance(msg, DoneMessage):
        return {
            "event": "done",
            "data": {"text": msg.text, "library_file": str(msg.library_file) if msg.library_file is not None else None, "severity": msg.severity},
        }
    if isinstance(msg, ErrorMessage):
        return {"event": "error", "data": {"text": msg.text, "details": msg.details}}
    return None


__all__ = [
    "AppConfig",
    "BackendController",
    "DataMessage",
    "AdevMessage",
    "StatusMessage",
    "DoneMessage",
    "ErrorMessage",
    "RecoverableAcquisitionErrorMessage",
]
