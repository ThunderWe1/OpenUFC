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
from laser_platform.scalar_adev import ScalarDiskAdevWorker
from laser_platform.stats import RollingStats
from laser_platform.ufc.allan import AllanResult
from laser_platform.wlm.bristol import BristolWavelengthMeterClient
from laser_platform.wlm.models import (
    WLM_CONNECTION_MODES,
    WLM_OPERATION_TIMEOUT_S,
    WLM_USB_RESOURCE,
    WavelengthMeterConfig,
    WavelengthMeterIdentity,
    WavelengthMeterResource,
    WavelengthSample,
    safe_wlm_sample_rate_hz,
)


WavelengthMeterClientFactory = Callable[[], BristolWavelengthMeterClient]


@dataclass(frozen=True)
class WlmStatusMessage:
    kind: str
    text: str


@dataclass(frozen=True)
class WlmSampleMessage:
    sample: WavelengthSample
    stats: dict[str, Any]


@dataclass(frozen=True)
class WlmAdevMessage:
    adev: AllanResult
    sample_count: int
    elapsed_s: float


@dataclass(frozen=True)
class WlmSessionOpenedMessage:
    library_file: Path


@dataclass(frozen=True)
class WlmDoneMessage:
    text: str
    library_file: Path | None


@dataclass(frozen=True)
class WlmErrorMessage:
    text: str
    details: str


def wlm_options(defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "wlm",
        "connection_modes": list(WLM_CONNECTION_MODES),
        "usb_resource": WLM_USB_RESOURCE,
        "defaults": dict(defaults),
    }


def wlm_resource_payload(
    settings: dict[str, Any],
    client_factory: WavelengthMeterClientFactory | None = None,
) -> dict[str, Any]:
    """Probe the configured endpoint; Bristol meters do not support discovery."""

    requested_resource = str(
        settings.get("resource", WLM_USB_RESOURCE) or WLM_USB_RESOURCE
    ).strip()
    resources: list[str] = []
    details: list[dict[str, Any]] = []
    error: str | None = None

    try:
        config = WavelengthMeterConfig.from_payload(settings)
    except Exception as exc:
        config = None
        error = str(exc)

    if config is not None:
        effective_resource = config.resource
        resources.append(effective_resource)
        try:
            client = (client_factory or BristolWavelengthMeterClient)()
            identity = _bounded_resource_probe(client, config)
            details.append(
                _resource_from_identity(
                    effective_resource,
                    identity,
                    available=True,
                ).to_dict()
            )
        except Exception as exc:
            error = str(exc)
            details.append(
                WavelengthMeterResource(
                    resource=effective_resource,
                    manufacturer="Bristol Instruments",
                    model="Wavelength Meter",
                    available=False,
                ).to_dict()
            )
    else:
        resources.append(requested_resource)
        details.append(
            WavelengthMeterResource(
                resource=requested_resource,
                manufacturer="Bristol Instruments",
                model="Wavelength Meter",
                available=False,
            ).to_dict()
        )

    return {
        "discovery_supported": False,
        "resources": resources,
        "resource_details": details,
        "error": error,
    }


class WlmAcquisitionWorker:
    def __init__(
        self,
        payload: dict[str, Any],
        out_queue: queue.Queue[object],
        client_factory: WavelengthMeterClientFactory | None = None,
    ) -> None:
        self.payload = payload
        self.out_queue = out_queue
        self.client_factory = client_factory or BristolWavelengthMeterClient
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name="wlm-acquisition-worker",
            daemon=True,
        )
        self._client: BristolWavelengthMeterClient | None = None
        self.library_file: Path | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        client = self._client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def _run(self) -> None:
        stats = RollingStats()
        writer: LmpWriter | None = None
        adev_worker: ScalarDiskAdevWorker | None = None
        try:
            config = WavelengthMeterConfig.from_payload(self.payload)
            client = self.client_factory()
            self._client = client
            identity = client.connect(config)
            sample_rate_hz = safe_wlm_sample_rate_hz(identity)
            sample_interval_s = 1.0 / sample_rate_hz
            self.out_queue.put(
                WlmStatusMessage("connected", f"Connected to {identity.raw}")
            )

            writer = LmpWriter(
                library_dir=Path(
                    str(self.payload.get("library_dir", "runs") or "runs")
                ).expanduser(),
                app_type="wlm",
                abbreviation="wlm",
                display_name=str(
                    self.payload.get("display_name", "") or ""
                ).strip(),
                instrument_id=identity.raw,
                resource=config.resource,
                unit="nm",
                sample_layout={
                    "kind": "elapsed_value_f64",
                    "record_size": int(SCALAR_RECORD_DTYPE.itemsize * 2),
                    "dtype": "<f8",
                    "value_semantic": "wavelength_nm",
                    "adev_semantic": "adev_nm",
                    "fields": [
                        {"name": "elapsed_s", "unit": "s"},
                        {"name": "wavelength_nm", "unit": "nm"},
                    ],
                },
                settings={
                    **config.as_dict(),
                    "sample_rate_hz": sample_rate_hz,
                },
                instrument_instance_id=str(
                    self.payload.get("instrument_instance_id", "") or ""
                ).strip(),
            )
            self.library_file = writer.path
            self.out_queue.put(WlmSessionOpenedMessage(writer.path))

            adev_worker = ScalarDiskAdevWorker(
                library_file=writer.path,
                default_sample_rate_hz=sample_rate_hz,
                out_queue=self.out_queue,
                result_factory=lambda result, count, elapsed: WlmAdevMessage(
                    result,
                    count,
                    elapsed,
                ),
                error_factory=lambda exc: WlmStatusMessage(
                    "warning",
                    f"Wavelength ADEV update failed: {exc}",
                ),
                thread_name="wlm-disk-adev-worker",
            )
            adev_worker.start()
            self.out_queue.put(WlmStatusMessage("running", "Acquisition started"))

            started = time.monotonic()
            next_sample = started
            while not self.stop_event.is_set():
                now = time.monotonic()
                if now < next_sample:
                    if self.stop_event.wait(next_sample - now):
                        break
                    continue

                try:
                    wavelength_nm = float(client.read_once())
                except Exception as exc:
                    if self.stop_event.is_set():
                        break
                    self.out_queue.put(
                        WlmStatusMessage(
                            "reconnecting",
                            f"{exc} Reconnecting to wavelength meter...",
                        )
                    )
                    if not self._attempt_reconnect(client, config):
                        break
                    self.out_queue.put(
                        WlmStatusMessage("running", "Wavelength meter reconnected")
                    )
                    next_sample = time.monotonic() + sample_interval_s
                    continue

                measured_at = time.monotonic()
                if not math.isfinite(wavelength_nm) or wavelength_nm <= 0:
                    self.out_queue.put(
                        WlmStatusMessage(
                            "warning",
                            "Ignored an invalid wavelength reading.",
                        )
                    )
                else:
                    next_sample_rate_hz = safe_wlm_sample_rate_hz(
                        identity,
                        wavelength_nm,
                    )
                    if next_sample_rate_hz != sample_rate_hz:
                        sample_rate_hz = next_sample_rate_hz
                        sample_interval_s = 1.0 / sample_rate_hz
                        writer.metadata["settings"]["sample_rate_hz"] = (
                            sample_rate_hz
                        )
                    sample = WavelengthSample(
                        elapsed_s=measured_at - started,
                        wavelength_nm=wavelength_nm,
                    )
                    writer.append_elapsed_value_sample(
                        sample.elapsed_s,
                        sample.wavelength_nm,
                    )
                    snapshot = stats.update(sample.wavelength_nm)
                    self.out_queue.put(WlmSampleMessage(sample, snapshot.to_dict()))

                next_sample = measured_at + sample_interval_s

            self.out_queue.put(
                WlmStatusMessage("stopping", "Stopping acquisition")
            )
            writer.close(ended_at=datetime.now(timezone.utc).isoformat())
            writer = None
            if adev_worker is not None:
                self.out_queue.put(
                    WlmStatusMessage(
                        "running",
                        "Final wavelength ADEV update from full file",
                    )
                )
                adev_worker.request_final_update()
                adev_worker.thread.join()
            self.out_queue.put(
                WlmDoneMessage("Stopped cleanly", self.library_file)
            )
        except Exception as exc:
            self.out_queue.put(WlmErrorMessage(str(exc), traceback.format_exc()))
        finally:
            if writer is not None:
                try:
                    writer.close(
                        ended_at=datetime.now(timezone.utc).isoformat()
                    )
                except Exception:
                    pass
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            if adev_worker is not None and adev_worker.thread.is_alive():
                adev_worker.stop()
                adev_worker.thread.join()
            self.library_file = None

    def _attempt_reconnect(
        self,
        client: BristolWavelengthMeterClient,
        config: WavelengthMeterConfig,
    ) -> bool:
        while not self.stop_event.is_set():
            try:
                client.close()
            except Exception:
                pass
            if self.stop_event.is_set():
                return False
            try:
                client.connect(config)
                return True
            except Exception as exc:
                self.out_queue.put(
                    WlmStatusMessage(
                        "reconnecting",
                        f"Reconnect failed: {exc}",
                    )
                )
                if self.stop_event.wait(2.0):
                    return False
        return False


class WlmController(AcquisitionController):
    def __init__(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        super().__init__(
            wlm_event_from_message, (WlmDoneMessage, WlmErrorMessage), "wlm-dispatcher", on_event
        )

    def start_acquisition(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None:
                raise RuntimeError(
                    "Wavelength Meter acquisition is already running"
                )
            worker = WlmAcquisitionWorker(payload, self.messages)
            self._worker = worker
        self.publish(
            "status",
            {"kind": "connecting", "text": "Connecting"},
        )
        worker.start()
        return {"ok": True}

    def stop_acquisition(self) -> dict[str, Any]:
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.stop()
            self.publish(
                "status",
                {"kind": "stopping", "text": "Stop requested"},
            )
        return {"ok": True}

    def shutdown(self) -> None:
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.stop()
            worker.thread.join()
        self._dispatcher_stop.set()
        self.messages.put(
            WlmStatusMessage(
                "stopping",
                "Wavelength Meter backend shutting down",
            )
        )


def wlm_event_from_message(message: object) -> dict[str, Any] | None:
    if isinstance(message, WlmStatusMessage):
        return {
            "event": "status",
            "data": {"kind": message.kind, "text": message.text},
        }
    if isinstance(message, WlmSessionOpenedMessage):
        return {
            "event": "session_opened",
            "data": {"library_file": str(message.library_file)},
        }
    if isinstance(message, WlmSampleMessage):
        return {
            "event": "sample",
            "data": {
                "elapsed_s": float(message.sample.elapsed_s),
                "wavelength_nm": float(message.sample.wavelength_nm),
                "unit": "nm",
                "stats": message.stats,
            },
        }
    if isinstance(message, WlmAdevMessage):
        return {
            "event": "adev",
            "data": {
                "tau_s": message.adev.tau_s.astype(float).tolist(),
                "adev_nm": message.adev.adev.astype(float).tolist(),
                "sample_count": int(message.sample_count),
                "elapsed_s": float(message.elapsed_s),
            },
        }
    if isinstance(message, WlmDoneMessage):
        return {
            "event": "done",
            "data": {
                "text": message.text,
                "library_file": (
                    str(message.library_file)
                    if message.library_file is not None
                    else None
                ),
            },
        }
    if isinstance(message, WlmErrorMessage):
        return {
            "event": "error",
            "data": {"text": message.text, "details": message.details},
        }
    return None


def _resource_from_identity(
    resource: str,
    identity: WavelengthMeterIdentity,
    *,
    available: bool,
) -> WavelengthMeterResource:
    return WavelengthMeterResource(
        resource=resource,
        manufacturer=identity.manufacturer,
        model=identity.model,
        serial=identity.serial,
        firmware=identity.firmware,
        available=available,
    )


def _bounded_resource_probe(
    client: BristolWavelengthMeterClient,
    config: WavelengthMeterConfig,
) -> WavelengthMeterIdentity:
    outcome: queue.Queue[
        tuple[WavelengthMeterIdentity | None, Exception | None]
    ] = queue.Queue(maxsize=1)

    def run_probe() -> None:
        identity: WavelengthMeterIdentity | None = None
        error: Exception | None = None
        try:
            identity = client.connect(config)
        except Exception as exc:
            error = exc
        finally:
            try:
                client.close()
            except Exception as exc:
                if error is None:
                    error = exc
        outcome.put((identity, error))

    probe_thread = threading.Thread(
        target=run_probe,
        name="wlm-resource-probe",
        daemon=True,
    )
    probe_thread.start()
    try:
        identity, error = outcome.get(timeout=WLM_OPERATION_TIMEOUT_S)
    except queue.Empty as exc:
        try:
            client.close()
        except Exception:
            pass
        raise TimeoutError(
            "Wavelength meter probe timed out after "
            f"{WLM_OPERATION_TIMEOUT_S:g} seconds."
        ) from exc
    if error is not None:
        raise error
    if identity is None:
        raise RuntimeError("Wavelength meter probe returned no identity.")
    return identity


__all__ = [
    "WlmAcquisitionWorker",
    "WlmController",
    "WlmStatusMessage",
    "wlm_event_from_message",
    "wlm_options",
    "wlm_resource_payload",
]
