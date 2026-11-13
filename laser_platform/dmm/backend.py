from __future__ import annotations

import math
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from laser_platform.controller import AcquisitionController
from laser_platform.dmm.instrument import DmmBatchConfigurationError, DmmBatchReadError, VisaInstrumentClient
from laser_platform.dmm.models import (
    DMM_MODEL_PROFILES,
    SUPPORTED_DMM_MODELS,
    DmmModelProfile,
    MeasurementConfig,
    MeasurementFunction,
    SampleRecord,
    resolve_dmm_resource,
)
from laser_platform.library import LmpWriter, SCALAR_RECORD_DTYPE
from laser_platform.scalar_adev import ScalarDiskAdevWorker
from laser_platform.stats import RollingStats
from laser_platform.ufc.allan import AllanResult


DMM_BATCH_TRANSFER_PERIOD_S = 1.0


def _dmm_batch_size(measurement: MeasurementConfig) -> int:
    interval_s = max(0.001, measurement.interval_ms / 1000.0)
    return max(1, int(round(DMM_BATCH_TRANSFER_PERIOD_S / interval_s)))


@dataclass(frozen=True)
class DmmStatusMessage:
    kind: str
    text: str


@dataclass(frozen=True)
class DmmSampleMessage:
    sample: SampleRecord
    stats: dict[str, Any]


@dataclass(frozen=True)
class DmmAdevMessage:
    adev: AllanResult
    sample_count: int
    elapsed_s: float


@dataclass(frozen=True)
class DmmSessionOpenedMessage:
    library_file: Path


@dataclass(frozen=True)
class DmmDoneMessage:
    text: str
    library_file: Path | None


@dataclass(frozen=True)
class DmmErrorMessage:
    text: str
    details: str


def _function_payload(
    fn: MeasurementFunction,
    profile: DmmModelProfile | None = None,
) -> dict[str, Any]:
    range_options = profile.ranges_for(fn) if profile is not None else fn.range_options
    return {
        "value": fn.value,
        "label": fn.label,
        "unit": fn.unit,
        "supports_nplc": fn.supports_nplc,
        "is_current": fn.is_current,
        "range_options": [{"label": label, "value": value} for label, value in range_options],
        "nplc_options": list(fn.nplc_options),
    }


def _model_profile_payload(profile: DmmModelProfile) -> dict[str, Any]:
    return {
        "model": profile.model,
        "supports_ascii_format": profile.supports_ascii_format,
        "current_terminals_a": list(profile.current_terminals_a),
        "functions": [_function_payload(fn, profile) for fn in MeasurementFunction],
    }


def dmm_options(defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        "functions": [_function_payload(fn) for fn in MeasurementFunction],
        "supported_models": list(SUPPORTED_DMM_MODELS),
        "model_profiles": {
            model: _model_profile_payload(DMM_MODEL_PROFILES[model])
            for model in SUPPORTED_DMM_MODELS
        },
        "defaults": dict(defaults),
    }


def _build_measurement_config(payload: dict[str, Any]) -> MeasurementConfig:
    fn = MeasurementFunction(str(payload.get("measurement_function", MeasurementFunction.VOLT_DC.value)))
    config = MeasurementConfig(
        function=fn,
        autorange=bool(payload.get("autorange", True)),
        range_value=float(payload.get("range_value", fn.range_options[0][1])),
        nplc=float(payload.get("nplc", 1.0)),
    )
    config.validate()
    return config


class DmmAcquisitionWorker:
    def __init__(
        self,
        payload: dict[str, Any],
        out_queue: queue.Queue[object],
    ) -> None:
        self.payload = payload
        self.out_queue = out_queue
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="dmm-acquisition-worker", daemon=True)
        self._client = None
        self.library_file: Path | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        client = self._client
        if client is not None:
            try:
                client.stop()
            except Exception:
                pass

    def _run(self) -> None:
        stats = RollingStats()
        writer: LmpWriter | None = None
        adev_worker: ScalarDiskAdevWorker | None = None
        connected = False
        client: VisaInstrumentClient | None = None
        try:
            resource = resolve_dmm_resource(self.payload.get("resource", ""))
            measurement = _build_measurement_config(self.payload)
            batch_size = _dmm_batch_size(measurement)
            sample_interval_s = measurement.interval_ms / 1000.0
            transfer_period_s = batch_size * sample_interval_s
            client = VisaInstrumentClient()
            self._client = client

            identity = client.connect(resource)
            connected = True
            self.out_queue.put(DmmStatusMessage("connected", f"Connected to {identity.raw}"))
            client.configure(measurement, batch_size=batch_size)

            library_dir = Path(str(self.payload.get("library_dir", "runs") or "runs")).expanduser()
            writer = LmpWriter(
                library_dir=library_dir,
                app_type="dmm",
                abbreviation="dmm",
                display_name=str(self.payload.get("display_name", "") or "").strip(),
                instrument_id=identity.raw,
                resource=resource,
                unit=measurement.function.unit,
                sample_layout={
                    "kind": "elapsed_value_f64",
                    "record_size": int(SCALAR_RECORD_DTYPE.itemsize * 2),
                    "dtype": "<f8",
                    "value_semantic": "value",
                    "adev_semantic": "adev",
                    "fields": [
                        {"name": "elapsed_s", "unit": "s"},
                        {"name": "value", "unit": measurement.function.unit},
                    ],
                },
                settings=measurement.as_dict(),
                instrument_instance_id=str(self.payload.get("instrument_instance_id", "") or "").strip(),
            )
            self.library_file = writer.path
            self.out_queue.put(DmmSessionOpenedMessage(writer.path))

            adev_worker = ScalarDiskAdevWorker(
                library_file=writer.path,
                default_sample_rate_hz=1000.0 / max(1.0, float(measurement.interval_ms)),
                out_queue=self.out_queue,
                result_factory=lambda result, count, elapsed: DmmAdevMessage(
                    result,
                    count,
                    elapsed,
                ),
                error_factory=lambda exc: DmmStatusMessage(
                    "warning",
                    f"DMM ADEV update failed: {exc}",
                ),
                thread_name="dmm-disk-adev-worker",
            )
            adev_worker.start()
            started = time.monotonic()
            client.start_sampling()
            self.out_queue.put(DmmStatusMessage("running", "Acquisition started"))

            sample_index = 0

            def append_batch(values) -> None:
                nonlocal sample_index
                for value in values:
                    sample = SampleRecord(
                        elapsed_s=sample_index * sample_interval_s,
                        value=float(value),
                        unit=measurement.function.unit,
                        function=measurement.function,
                    )
                    writer.append_elapsed_value_sample(sample.elapsed_s, sample.value)
                    snapshot = stats.update(sample.value)
                    self.out_queue.put(DmmSampleMessage(sample, snapshot.to_dict()))
                    sample_index += 1

            while not self.stop_event.is_set():
                if self.stop_event.wait(transfer_period_s):
                    break
                try:
                    values = client.read_batch(batch_size)
                except DmmBatchReadError:
                    raise
                except Exception as exc:
                    self.out_queue.put(DmmStatusMessage("reconnecting", f"{exc} Reconnecting to instrument..."))
                    if not self._attempt_reconnect(client, resource, measurement, batch_size):
                        self.out_queue.put(DmmErrorMessage("Instrument connection could not be restored", traceback.format_exc()))
                        return
                    sample_index = max(sample_index, math.floor((time.monotonic() - started) / sample_interval_s))
                    self.out_queue.put(DmmStatusMessage("running", "Instrument reconnected"))
                    continue

                append_batch(values)

            self.out_queue.put(DmmStatusMessage("stopping", "Stopping acquisition"))
            client.stop()
            while True:
                pending = client.points_available()
                if pending <= 0:
                    break
                values = client.read_batch(min(batch_size, pending))
                if not values.size:
                    raise RuntimeError("DMM batch drain made no progress")
                append_batch(values)

            ended_at = datetime.now(timezone.utc).isoformat()
            if writer is not None:
                writer.close(ended_at=ended_at)
                writer = None
            if adev_worker is not None:
                self.out_queue.put(DmmStatusMessage("running", "Final DMM ADEV update from full file"))
                adev_worker.request_final_update()
                adev_worker.thread.join(timeout=300.0)
            self.out_queue.put(DmmDoneMessage("Stopped cleanly", self.library_file))
        except Exception as exc:
            self.out_queue.put(DmmErrorMessage(str(exc), traceback.format_exc()))
        finally:
            ended_at = datetime.now(timezone.utc).isoformat()
            if writer is not None:
                try:
                    writer.close(ended_at=ended_at)
                except Exception:
                    pass
            if self._client is not None:
                try:
                    if connected:
                        self._client.stop()
                    self._client.close()
                except Exception:
                    pass
            if adev_worker is not None and adev_worker.thread.is_alive():
                adev_worker.stop()
                adev_worker.thread.join(timeout=2.0)
            self.library_file = None

    def _attempt_reconnect(
        self,
        client: Any,
        resource: str,
        measurement: MeasurementConfig,
        batch_size: int,
    ) -> bool:
        while not self.stop_event.is_set():
            try:
                client.close()
                client.connect(resource)
                client.configure(measurement, batch_size=batch_size)
                client.start_sampling()
                return True
            except DmmBatchConfigurationError:
                return False
            except Exception as exc:
                self.out_queue.put(DmmStatusMessage("reconnecting", f"Reconnect failed: {exc}"))
                if self.stop_event.wait(2.0):
                    return False
        return False


class DmmController(AcquisitionController):
    def __init__(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        super().__init__(
            dmm_event_from_message, (DmmDoneMessage, DmmErrorMessage), "dmm-dispatcher", on_event
        )

    def start_acquisition(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None:
                raise RuntimeError("DMM acquisition is already running")
            worker = DmmAcquisitionWorker(payload, self.messages)
            self._worker = worker
        self.publish("status", {"kind": "connecting", "text": "Connecting"})
        worker.start()
        return {"ok": True}

    def stop_acquisition(self) -> dict[str, Any]:
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.stop()
            self.publish("status", {"kind": "stopping", "text": "Stop requested"})
        return {"ok": True}

    def shutdown(self) -> None:
        self.stop_acquisition()
        self._dispatcher_stop.set()
        self.messages.put(DmmStatusMessage("stopping", "DMM backend shutting down"))


def dmm_event_from_message(msg: object) -> dict[str, Any] | None:
    if isinstance(msg, DmmStatusMessage):
        return {"event": "status", "data": {"kind": msg.kind, "text": msg.text}}
    if isinstance(msg, DmmSessionOpenedMessage):
        return {
            "event": "session_opened",
            "data": {
                "library_file": str(msg.library_file),
            },
        }
    if isinstance(msg, DmmSampleMessage):
        sample = msg.sample
        return {
            "event": "sample",
            "data": {
                "elapsed_s": float(sample.elapsed_s),
                "value": float(sample.value),
                "unit": sample.unit,
                "function": sample.function.value,
                "stats": msg.stats,
            },
        }
    if isinstance(msg, DmmAdevMessage):
        return {
            "event": "adev",
            "data": {
                "tau_s": msg.adev.tau_s.astype(float).tolist(),
                "adev": msg.adev.adev.astype(float).tolist(),
                "sample_count": int(msg.sample_count),
                "elapsed_s": float(msg.elapsed_s),
            },
        }
    if isinstance(msg, DmmDoneMessage):
        return {
            "event": "done",
            "data": {
                "text": msg.text,
                "library_file": str(msg.library_file) if msg.library_file is not None else None,
            },
        }
    if isinstance(msg, DmmErrorMessage):
        return {"event": "error", "data": {"text": msg.text, "details": msg.details}}
    return None


__all__ = ["DmmController", "dmm_options"]
