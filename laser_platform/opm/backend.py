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
from laser_platform.library import LmpWriter, SCALAR_RECORD_DTYPE
from laser_platform.opm.client import PowerMeterDriverUnavailable
from laser_platform.opm.models import (
    DISPLAY_UNITS,
    OPM_SAFE_SAMPLE_RATE_HZ,
    POWER_RANGE_OPTIONS,
    PowerMeterConfig,
    PowerMeterResource,
    PowerSample,
)
from laser_platform.opm.tlpmx import TlpmxPowerMeterClient
from laser_platform.scalar_adev import ScalarDiskAdevWorker
from laser_platform.stats import RollingStats
from laser_platform.ufc.allan import AllanResult


@dataclass(frozen=True)
class OpmStatusMessage:
    kind: str
    text: str


@dataclass(frozen=True)
class OpmSampleMessage:
    sample: PowerSample
    stats: dict[str, Any]


@dataclass(frozen=True)
class OpmAdevMessage:
    adev: AllanResult
    sample_count: int
    elapsed_s: float


@dataclass(frozen=True)
class OpmSessionOpenedMessage:
    library_file: Path


@dataclass(frozen=True)
class OpmDoneMessage:
    text: str
    library_file: Path | None


@dataclass(frozen=True)
class OpmErrorMessage:
    text: str
    details: str


def opm_options(defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "opm",
        "units": list(DISPLAY_UNITS),
        "range_options": [
            {"label": label, "value": value}
            for label, value in POWER_RANGE_OPTIONS
        ],
        "defaults": dict(defaults),
    }


def opm_resource_payload(
    client_factory: Callable[[], TlpmxPowerMeterClient] | None = None,
) -> dict[str, Any]:
    real_resources: list[PowerMeterResource] = []
    error: str | None = None
    error_code: str | None = None
    driver_available = False
    client: TlpmxPowerMeterClient | None = None
    try:
        client = (client_factory or TlpmxPowerMeterClient)()
        real_resources = list(client.discover_resources())
        driver_available = True
    except PowerMeterDriverUnavailable as exc:
        error = str(exc)
        error_code = "tlpmx_driver_unavailable"
    except Exception as exc:
        error = str(exc)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    details = [resource.to_dict() for resource in real_resources]
    resources = [resource.resource for resource in real_resources]
    return {
        "resources": resources,
        "resource_details": details,
        "driver_available": driver_available,
        "error": error,
        "error_code": error_code,
    }


class OpmAcquisitionWorker:
    def __init__(
        self,
        payload: dict[str, Any],
        out_queue: queue.Queue[object],
    ) -> None:
        self.payload = payload
        self.out_queue = out_queue
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="opm-acquisition-worker", daemon=True)
        self._client: TlpmxPowerMeterClient | None = None
        self.library_file: Path | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        stats = RollingStats()
        writer: LmpWriter | None = None
        adev_worker: ScalarDiskAdevWorker | None = None
        try:
            config = PowerMeterConfig.from_payload(self.payload)
            client = TlpmxPowerMeterClient()
            self._client = client
            identity = client.connect(config)
            client.configure(config)
            sample_rate_hz = OPM_SAFE_SAMPLE_RATE_HZ
            sample_interval_s = 1.0 / sample_rate_hz
            self.out_queue.put(OpmStatusMessage("connected", f"Connected to {identity.raw}"))

            writer = LmpWriter(
                library_dir=Path(str(self.payload.get("library_dir", "runs") or "runs")).expanduser(),
                app_type="opm",
                abbreviation="opm",
                display_name=str(self.payload.get("display_name", "") or "").strip(),
                instrument_id=identity.raw,
                resource=config.resource,
                unit="W",
                sample_layout={
                    "kind": "elapsed_value_f64",
                    "record_size": int(SCALAR_RECORD_DTYPE.itemsize * 2),
                    "dtype": "<f8",
                    "value_semantic": "power_w",
                    "adev_semantic": "adev_w",
                    "fields": [
                        {"name": "elapsed_s", "unit": "s"},
                        {"name": "power_w", "unit": "W"},
                    ],
                },
                settings={
                    **config.as_dict(),
                    "sample_rate_hz": sample_rate_hz,
                },
                instrument_instance_id=str(self.payload.get("instrument_instance_id", "") or "").strip(),
            )
            self.library_file = writer.path
            self.out_queue.put(OpmSessionOpenedMessage(writer.path))

            adev_worker = ScalarDiskAdevWorker(
                library_file=writer.path,
                default_sample_rate_hz=sample_rate_hz,
                out_queue=self.out_queue,
                result_factory=lambda result, count, elapsed: OpmAdevMessage(
                    result,
                    count,
                    elapsed,
                ),
                error_factory=lambda exc: OpmStatusMessage(
                    "warning",
                    f"Optical power ADEV update failed: {exc}",
                ),
                thread_name="opm-disk-adev-worker",
            )
            adev_worker.start()
            self.out_queue.put(OpmStatusMessage("running", "Acquisition started"))
            started = time.monotonic()
            next_sample = started

            while not self.stop_event.is_set():
                now = time.monotonic()
                if now < next_sample:
                    if self.stop_event.wait(next_sample - now):
                        break
                    continue

                try:
                    value_w = float(client.read_once())
                except Exception as exc:
                    self.out_queue.put(
                        OpmStatusMessage("reconnecting", f"{exc} Reconnecting to optical power meter...")
                    )
                    if not self._attempt_reconnect(client, config):
                        break
                    self.out_queue.put(OpmStatusMessage("running", "Optical power meter reconnected"))
                    next_sample = time.monotonic() + sample_interval_s
                    continue

                measured_at = time.monotonic()
                if not math.isfinite(value_w):
                    self.out_queue.put(
                        OpmStatusMessage("warning", "Ignored a non-finite optical power reading.")
                    )
                else:
                    sample = PowerSample(
                        elapsed_s=measured_at - started,
                        power_w=value_w,
                    )
                    writer.append_elapsed_value_sample(sample.elapsed_s, sample.power_w)
                    snapshot = stats.update(sample.power_w)
                    self.out_queue.put(OpmSampleMessage(sample, snapshot.to_dict()))

                next_sample = measured_at + sample_interval_s

            self.out_queue.put(OpmStatusMessage("stopping", "Stopping acquisition"))
            ended_at = datetime.now(timezone.utc).isoformat()
            writer.close(ended_at=ended_at)
            writer = None
            if adev_worker is not None:
                self.out_queue.put(OpmStatusMessage("running", "Final optical power ADEV update from full file"))
                adev_worker.request_final_update()
                adev_worker.thread.join(timeout=300.0)
            self.out_queue.put(OpmDoneMessage("Stopped cleanly", self.library_file))
        except Exception as exc:
            self.out_queue.put(OpmErrorMessage(str(exc), traceback.format_exc()))
        finally:
            if writer is not None:
                try:
                    writer.close(ended_at=datetime.now(timezone.utc).isoformat())
                except Exception:
                    pass
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            if adev_worker is not None and adev_worker.thread.is_alive():
                adev_worker.stop()
                adev_worker.thread.join(timeout=2.0)
            self.library_file = None

    def _attempt_reconnect(self, client: TlpmxPowerMeterClient, config: PowerMeterConfig) -> bool:
        while not self.stop_event.is_set():
            try:
                client.close()
            except Exception:
                pass
            try:
                client.connect(config)
                client.configure(config)
                return True
            except Exception as exc:
                self.out_queue.put(OpmStatusMessage("reconnecting", f"Reconnect failed: {exc}"))
                if self.stop_event.wait(2.0):
                    return False
        return False


class OpmController(AcquisitionController):
    def __init__(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        super().__init__(
            opm_event_from_message, (OpmDoneMessage, OpmErrorMessage), "opm-dispatcher", on_event
        )

    def start_acquisition(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None:
                raise RuntimeError("Optical Power Meter acquisition is already running")
            worker = OpmAcquisitionWorker(payload, self.messages)
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
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.stop()
            worker.thread.join(timeout=6.0)
        self._dispatcher_stop.set()
        self.messages.put(OpmStatusMessage("stopping", "Optical Power Meter backend shutting down"))


def opm_event_from_message(message: object) -> dict[str, Any] | None:
    if isinstance(message, OpmStatusMessage):
        return {"event": "status", "data": {"kind": message.kind, "text": message.text}}
    if isinstance(message, OpmSessionOpenedMessage):
        return {"event": "session_opened", "data": {"library_file": str(message.library_file)}}
    if isinstance(message, OpmSampleMessage):
        return {
            "event": "sample",
            "data": {
                "elapsed_s": float(message.sample.elapsed_s),
                "power_w": float(message.sample.power_w),
                "unit": "W",
                "stats": message.stats,
            },
        }
    if isinstance(message, OpmAdevMessage):
        return {
            "event": "adev",
            "data": {
                "tau_s": message.adev.tau_s.astype(float).tolist(),
                "adev_w": message.adev.adev.astype(float).tolist(),
                "sample_count": int(message.sample_count),
                "elapsed_s": float(message.elapsed_s),
            },
        }
    if isinstance(message, OpmDoneMessage):
        return {
            "event": "done",
            "data": {
                "text": message.text,
                "library_file": str(message.library_file) if message.library_file is not None else None,
            },
        }
    if isinstance(message, OpmErrorMessage):
        return {"event": "error", "data": {"text": message.text, "details": message.details}}
    return None
__all__ = [
    "OpmAcquisitionWorker",
    "OpmController",
    "opm_event_from_message",
    "opm_options",
    "opm_resource_payload",
]
