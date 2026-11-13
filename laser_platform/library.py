"""Shared library storage for Laser Measurement Platform acquisitions."""

from __future__ import annotations

import csv
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from laser_platform.stats import estimated_sample_rate
from laser_platform.ufc.allan import AllanResult, frequency_file_adev, non_overlapping_adev


MAGIC = b"LMP1"
HEADER_SIZE = 64 * 1024
PAYLOAD_OFFSET = len(MAGIC) + HEADER_SIZE
UFC_SAMPLE_DTYPE = np.dtype("<f8")
SCALAR_RECORD_DTYPE = np.dtype("<f8")
SCALAR_LAYOUT_KIND = "elapsed_value_f64"


class LmpWriter:
    """Append-only writer for one `.lmp` acquisition file."""

    def __init__(
        self,
        library_dir: Path,
        app_type: str,
        abbreviation: str,
        display_name: str,
        instrument_id: str,
        resource: str,
        unit: str,
        sample_layout: dict[str, Any],
        settings: dict[str, Any],
        instrument_instance_id: str | None = None,
    ) -> None:
        self.library_dir = Path(library_dir).expanduser()
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.path = self._unique_path(abbreviation)
        self.metadata = {
            "schema_version": 1,
            "format": "lmp",
            "app_type": app_type,
            "instrument_abbreviation": abbreviation,
            "display_name": str(display_name or "").strip(),
            "file_name": self.path.name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": None,
            "instrument_id": instrument_id,
            "resource": resource,
            "sample_count": 0,
            "unit": unit,
            "sample_layout": sample_layout,
            "settings": settings,
        }
        if instrument_instance_id:
            self.metadata["instrument_instance_id"] = str(instrument_instance_id)
        if app_type == "ufc":
            self.metadata["ufc_segment_starts"] = [0]
        _validate_metadata(self.metadata)
        with self.path.open("xb") as handle:
            handle.write(MAGIC)
            handle.write(_encode_header(self.metadata))
        self._file = self.path.open("r+b")
        self._file.seek(PAYLOAD_OFFSET)
        self._sample_count = 0
        self._last_metadata_write = 0.0

    @property
    def sample_count(self) -> int:
        return self._sample_count

    def append_ufc_frequency(self, values: np.ndarray | Iterable[float]) -> None:
        data = np.asarray(values, dtype=np.float64)
        if data.size == 0:
            return
        self._file.write(data.astype(UFC_SAMPLE_DTYPE, copy=False).tobytes())
        self._file.flush()
        self._sample_count += int(data.size)
        self.metadata["sample_count"] = self._sample_count
        self._write_metadata()

    def mark_ufc_segment_start(self) -> None:
        """Persist a discontinuity before appending any following readings."""
        starts = self.metadata["ufc_segment_starts"]
        if self._sample_count > starts[-1]:
            starts.append(self._sample_count)
        self._write_metadata(force=True)

    def append_elapsed_value_sample(self, elapsed_s: float, value: float) -> None:
        data = np.asarray([float(elapsed_s), float(value)], dtype=np.float64)
        self._file.write(data.astype(SCALAR_RECORD_DTYPE, copy=False).tobytes())
        self._file.flush()
        self._sample_count += 1
        self.metadata["sample_count"] = self._sample_count
        self._write_metadata()

    def close(self, ended_at: str | None = None) -> None:
        if not self._file.closed:
            self._file.flush()
            self._file.close()
        self.metadata["sample_count"] = self._sample_count
        self.metadata["ended_at"] = ended_at or datetime.now(timezone.utc).isoformat()
        self._write_metadata(force=True)

    def _write_metadata(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_metadata_write < 2.0:
            return
        write_metadata(self.path, self.metadata)
        self._last_metadata_write = now

    def _unique_path(self, abbreviation: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = self.library_dir / f"{abbreviation}_{stamp}.lmp"
        if not candidate.exists():
            return candidate
        for index in range(1, 1000):
            candidate = self.library_dir / f"{abbreviation}_{stamp}_{index:03d}.lmp"
            if not candidate.exists():
                return candidate
        raise RuntimeError("could not create a unique library file")


def _encode_header(metadata: dict[str, Any]) -> bytes:
    raw = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > HEADER_SIZE:
        raise ValueError("LMP metadata exceeds the fixed 64 KiB header")
    return raw + (b"\0" * (HEADER_SIZE - len(raw)))


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path = Path(path)
    with path.open("r+b") as handle:
        if handle.read(len(MAGIC)) != MAGIC:
            raise ValueError("invalid LMP file magic")
        handle.seek(len(MAGIC))
        handle.write(_encode_header(metadata))
        handle.flush()
        os.fsync(handle.fileno())


def _validate_metadata(metadata: dict[str, Any]) -> None:
    try:
        if type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1 or metadata["format"] != "lmp":
            raise ValueError("unsupported LMP format version")
        app_type = metadata["app_type"]
        if app_type not in {"ufc", "dmm", "opm", "wlm"}:
            raise ValueError("unsupported LMP instrument type")
        layout, settings = metadata["sample_layout"], metadata["settings"]
        expected_kind, expected_size = ("ufc_frequency_f64", 8) if app_type == "ufc" else (SCALAR_LAYOUT_KIND, 16)
        if layout["kind"] != expected_kind or layout["record_size"] != expected_size or layout["dtype"] != "<f8":
            raise ValueError("invalid LMP sample layout")
        semantics = ("adev_semantic",) if app_type == "ufc" else ("adev_semantic", "value_semantic")
        for key in semantics:
            if not isinstance(layout[key], str) or not layout[key].strip():
                raise ValueError(f"LMP sample layout requires {key}")
        if not isinstance(metadata["unit"], str) or not metadata["unit"]:
            raise ValueError("LMP recording requires a measurement unit")
        numeric_keys = ("sample_rate_hz", "optical_frequency_hz") if app_type == "ufc" else (
            ("interval_ms",) if app_type == "dmm" else ("sample_rate_hz",)
        )
        for key in numeric_keys:
            value = settings[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"LMP {key} must be a finite positive number")
        if app_type == "ufc":
            for key in ("divide_adev_by_optical_frequency", "divide_adev_by_sqrt2"):
                if type(settings[key]) is not bool:
                    raise ValueError(f"LMP {key} must be boolean")
            # Early LMP1 files have no boundary tracking; keep that absence intact.
            starts = metadata.get("ufc_segment_starts", [0])
            if (not isinstance(starts, list) or not starts or starts[0] != 0
                    or any(type(start) is not int for start in starts)
                    or any(right <= left for left, right in zip(starts, starts[1:]))):
                raise ValueError("LMP segment starts must be increasing sample offsets beginning at zero")
        elif app_type == "dmm" and not isinstance(settings["measurement_function"], str):
            raise ValueError("LMP DMM recording requires a measurement function")
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid LMP metadata; current-format fields are required: {exc}") from exc


def read_metadata(path: Path) -> dict[str, Any]:
    path = Path(path)
    with path.open("rb") as handle:
        if handle.read(len(MAGIC)) != MAGIC:
            raise ValueError("invalid LMP file magic")
        raw = handle.read(HEADER_SIZE)
    payload = raw.split(b"\0", 1)[0]
    if not payload:
        raise ValueError("missing LMP metadata")
    metadata = json.loads(payload.decode("utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("invalid LMP metadata")
    _validate_metadata(metadata)
    if metadata["app_type"] == "ufc" and metadata.get("ufc_segment_starts", [0])[-1] > sample_count_from_size(path, metadata):
        raise ValueError("LMP segment starts exceed the recorded sample count")
    return metadata


def sample_count_from_size(path: Path, metadata: dict[str, Any]) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    payload_size = max(0, path.stat().st_size - PAYLOAD_OFFSET)
    record_size = int(metadata["sample_layout"]["record_size"])
    if record_size <= 0:
        raise ValueError("LMP sample record size must be greater than zero")
    return payload_size // record_size


def list_library_files(library_dir: Path, active_paths: Iterable[Path] = ()) -> dict[str, Any]:
    library_dir = Path(library_dir).expanduser().resolve()
    active = _normalized_paths(active_paths)
    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    if library_dir.exists():
        for path in library_dir.iterdir():
            if path.suffix.lower() != ".lmp" or not path.is_file():
                continue
            try:
                metadata = read_metadata(path)
                count = sample_count_from_size(path, metadata)
                stat = path.stat()
            except Exception as exc:
                warnings.append(f"Could not read {path.name}: {exc}")
                continue
            items.append(
                {
                    "file": path.name,
                    "path": str(path),
                    "display_name": metadata.get("display_name", ""),
                    "app_type": metadata.get("app_type", ""),
                    "instrument_abbreviation": metadata.get("instrument_abbreviation", ""),
                    "started_at": metadata.get("started_at"),
                    "ended_at": metadata.get("ended_at"),
                    "instrument_id": metadata.get("instrument_id", ""),
                    "resource": metadata.get("resource", ""),
                    "unit": metadata.get("unit", ""),
                    "sample_count": int(count),
                    "size_bytes": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "active": _normalize_path(path) in active,
                }
            )
    items.sort(key=lambda item: item.get("modified_at") or "", reverse=True)
    return {"library_dir": str(library_dir), "items": items, "warnings": warnings}


def library_item_preview(library_dir: Path, file_name: str, max_points: int = 1200) -> dict[str, Any]:
    path = _library_file_path(library_dir, file_name)
    metadata = read_metadata(path)
    count = sample_count_from_size(path, metadata)
    metadata = {**metadata, "sample_count": int(count)}
    return {
        "file": path.name,
        "path": str(path),
        "metadata": metadata,
        "waveform": _waveform_preview(path, metadata, max_points=max_points),
        "adev": _adev_preview(path, metadata, max_points=max_points),
    }


def library_waveform_preview(library_dir: Path, file_name: str, max_points: int = 1200) -> dict[str, Any]:
    path = _library_file_path(library_dir, file_name)
    metadata = read_metadata(path)
    count = sample_count_from_size(path, metadata)
    return {
        "file": path.name,
        "sample_count": int(count),
        "waveform": _waveform_preview(path, metadata, max_points=max_points),
    }


def library_frequency_noise(library_dir: Path, file_name: str, **parameters) -> dict[str, Any]:
    from laser_platform.ufc.spectrum import frequency_noise_psd

    path = _library_file_path(library_dir, file_name)
    # Snapshot the length before reading metadata: any boundary within this
    # prefix was persisted before its samples, even while acquisition continues.
    count = max(0, path.stat().st_size - PAYLOAD_OFFSET) // UFC_SAMPLE_DTYPE.itemsize
    metadata = read_metadata(path)
    if metadata["sample_layout"]["kind"] != "ufc_frequency_f64":
        raise ValueError("Frequency noise requires frequency-counter measurements")
    start = max(0, count - 65536)
    with path.open("rb") as handle:
        handle.seek(PAYLOAD_OFFSET + start * UFC_SAMPLE_DTYPE.itemsize)
        values = np.frombuffer(handle.read((count - start) * UFC_SAMPLE_DTYPE.itemsize), dtype=UFC_SAMPLE_DTYPE)
    result = frequency_noise_psd(
        values, float(metadata["settings"]["sample_rate_hz"]),
        segment_starts=[int(i) - start for i in metadata.get("ufc_segment_starts", [0]) if start < int(i) < count],
        **parameters,
    )
    return {**result, "total_samples": count, "sample_limit": 65536}


def rename_library_item(library_dir: Path, file_name: str, display_name: str) -> dict[str, Any]:
    path = _library_file_path(library_dir, file_name)
    metadata = read_metadata(path)
    metadata["display_name"] = str(display_name or "").strip()
    write_metadata(path, metadata)
    return {"ok": True, "file": path.name, "display_name": metadata["display_name"]}


def delete_library_item(library_dir: Path, file_name: str, active_paths: Iterable[Path] = ()) -> dict[str, Any]:
    path = _library_file_path(library_dir, file_name)
    if _normalize_path(path) in _normalized_paths(active_paths):
        raise RuntimeError("Cannot delete an acquisition file that is still being written")
    path.unlink()
    return {"ok": True, "file": path.name}


def export_library_series(library_dir: Path, file_name: str, series: str, csv_path: Path) -> dict[str, Any]:
    source_path = _library_file_path(library_dir, file_name)
    output_path = Path(csv_path).expanduser()
    if not str(output_path).strip():
        raise ValueError("Choose an output CSV path")
    if output_path.exists() and output_path.samefile(source_path):
        raise ValueError("CSV output must not overwrite the source recording")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = read_metadata(source_path)
    count = sample_count_from_size(source_path, metadata)
    if series == "waveform":
        rows = _export_waveform_csv(source_path, metadata, count, output_path)
    elif series == "adev":
        rows = _export_adev_csv(source_path, metadata, count, output_path)
    else:
        raise ValueError("series must be 'waveform' or 'adev'")
    return {"ok": True, "csv_path": str(output_path), "row_count": int(rows)}


def _library_file_path(library_dir: Path, file_name: str) -> Path:
    library_dir = Path(library_dir).expanduser()
    name = Path(str(file_name)).name
    if not name.lower().endswith(".lmp"):
        raise ValueError("library item must be a .lmp file")
    path = (library_dir / name).resolve()
    root = library_dir.resolve()
    if path.parent != root:
        raise ValueError("invalid library item path")
    if not path.exists():
        raise FileNotFoundError(f"library item not found: {name}")
    return path


def _normalized_paths(paths: Iterable[Path]) -> set[str]:
    return {_normalize_path(path) for path in paths if path is not None}


def _normalize_path(path: Path) -> str:
    return str(Path(path).expanduser().resolve()).casefold()


def _waveform_preview(path: Path, metadata: dict[str, Any], max_points: int) -> dict[str, Any]:
    count = sample_count_from_size(path, metadata)
    if count <= 0:
        return {"unit": metadata.get("unit", ""), "points": []}
    indices = _preview_indices(count, max_points)
    kind = metadata["sample_layout"]["kind"]
    if kind == "ufc_frequency_f64":
        sample_rate = float(metadata["settings"]["sample_rate_hz"])
        data = np.memmap(path, dtype=UFC_SAMPLE_DTYPE, mode="r", offset=PAYLOAD_OFFSET, shape=(count,))
        starts = sorted(metadata.get("ufc_segment_starts", [0]))
        segments = np.searchsorted(starts, indices, side="right")
        points = []
        for position, index in enumerate(indices):
            if position and segments[position] != segments[position - 1]:
                points.append({"x": float(index) / sample_rate, "y": None})
            points.append({"x": float(index) / sample_rate, "y": float(data[index])})
        del data
        return {"unit": metadata.get("unit", "Hz"), "points": points}
    if kind == SCALAR_LAYOUT_KIND:
        data = np.memmap(path, dtype=SCALAR_RECORD_DTYPE, mode="r", offset=PAYLOAD_OFFSET, shape=(count, 2))
        points = [{"x": float(data[index, 0]), "y": float(data[index, 1])} for index in indices]
        del data
        return {"unit": metadata.get("unit", ""), "points": points}
    raise ValueError("unsupported LMP sample layout")


def _adev_preview(path: Path, metadata: dict[str, Any], max_points: int) -> dict[str, Any]:
    count = sample_count_from_size(path, metadata)
    if count < 4:
        return {"unit": _adev_unit(metadata), "points": []}
    result = _calculate_adev(path, metadata, count, max_samples=max(4, min(50_000, max_points * 40)))
    return {"unit": _adev_unit(metadata), "points": _adev_points(result)}


def _calculate_adev(path: Path, metadata: dict[str, Any], count: int, max_samples: int | None = None) -> AllanResult:
    if count < 4:
        empty_float = np.array([], dtype=np.float64)
        empty_int = np.array([], dtype=np.int64)
        return AllanResult(empty_float, empty_float, empty_int, empty_int)
    kind = metadata["sample_layout"]["kind"]
    settings = metadata["settings"]
    if kind == "ufc_frequency_f64":
        sample_rate = float(settings["sample_rate_hz"])
        sample_count = int(count)
        if max_samples is not None and sample_count > max_samples:
            data = np.memmap(path, dtype=UFC_SAMPLE_DTYPE, mode="r", offset=PAYLOAD_OFFSET, shape=(sample_count,))
            indices = _preview_indices(sample_count, max_samples)
            values = np.asarray(data[indices], dtype=np.float64)
            del data
            effective_rate = sample_rate * (len(indices) - 1) / max(1, indices[-1] - indices[0])
            from laser_platform.ufc.allan import frequency_adev

            return frequency_adev(
                values,
                sample_rate_hz=effective_rate,
                optical_frequency_hz=float(settings["optical_frequency_hz"]),
                divide_by_optical_frequency=bool(settings["divide_adev_by_optical_frequency"]),
                divide_by_sqrt2=bool(settings["divide_adev_by_sqrt2"]),
                segment_starts=np.searchsorted(indices, metadata.get("ufc_segment_starts", [0])).tolist(),
            )
        return frequency_file_adev(
            path,
            sample_count=sample_count,
            sample_rate_hz=sample_rate,
            optical_frequency_hz=float(settings["optical_frequency_hz"]),
            dtype=UFC_SAMPLE_DTYPE,
            offset=PAYLOAD_OFFSET,
            divide_by_optical_frequency=bool(settings["divide_adev_by_optical_frequency"]),
            divide_by_sqrt2=bool(settings["divide_adev_by_sqrt2"]),
            segment_starts=metadata.get("ufc_segment_starts", [0]),
        )
    if kind == SCALAR_LAYOUT_KIND:
        sample_count = int(count)
        data = np.memmap(path, dtype=SCALAR_RECORD_DTYPE, mode="r", offset=PAYLOAD_OFFSET, shape=(sample_count, 2))
        if max_samples is not None and sample_count > max_samples:
            indices = _preview_indices(sample_count, max_samples)
            elapsed = np.asarray(data[indices, 0], dtype=np.float64)
            values = np.asarray(data[indices, 1], dtype=np.float64)
        else:
            elapsed = np.asarray(data[:, 0], dtype=np.float64)
            values = np.asarray(data[:, 1], dtype=np.float64)
        del data
        default_sample_rate = 1000.0 / settings["interval_ms"] if metadata["app_type"] == "dmm" else settings["sample_rate_hz"]
        sample_rate = estimated_sample_rate(elapsed, default_hz=default_sample_rate)
        return non_overlapping_adev(values, sample_rate_hz=sample_rate)
    raise ValueError("unsupported LMP sample layout")


def _export_waveform_csv(path: Path, metadata: dict[str, Any], count: int, output_path: Path, chunk_samples: int = 200_000) -> int:
    kind = metadata["sample_layout"]["kind"]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if kind == "ufc_frequency_f64":
            sample_rate = float(metadata["settings"]["sample_rate_hz"])
            starts = sorted(metadata.get("ufc_segment_starts", [0]))
            segmented = len(starts) > 1
            writer.writerow(["sample_index", "time_s", "frequency_hz"] + (["segment_index"] if segmented else []))
            if count == 0:
                return 0
            data = np.memmap(path, dtype=UFC_SAMPLE_DTYPE, mode="r", offset=PAYLOAD_OFFSET, shape=(count,))
            written = 0
            for start in range(0, count, chunk_samples):
                end = min(count, start + chunk_samples)
                indices = np.arange(start, end, dtype=np.int64)
                times = indices / sample_rate
                values = np.asarray(data[start:end], dtype=np.float64)
                columns = [indices.tolist(), times.tolist(), values.tolist()]
                if segmented:
                    columns.append((np.searchsorted(starts, indices, side="right") - 1).tolist())
                writer.writerows(zip(*columns))
                written += int(end - start)
            del data
            return written
        if kind == SCALAR_LAYOUT_KIND:
            layout = metadata["sample_layout"]
            value_heading = str(layout["value_semantic"]).strip()
            if not value_heading:
                raise ValueError("LMP scalar layout requires a value semantic")
            writer.writerow(["sample_index", "elapsed_s", value_heading])
            if count == 0:
                return 0
            data = np.memmap(path, dtype=SCALAR_RECORD_DTYPE, mode="r", offset=PAYLOAD_OFFSET, shape=(count, 2))
            written = 0
            for start in range(0, count, chunk_samples):
                end = min(count, start + chunk_samples)
                indices = np.arange(start, end, dtype=np.int64)
                rows = zip(indices.tolist(), data[start:end, 0].astype(float).tolist(), data[start:end, 1].astype(float).tolist())
                writer.writerows(rows)
                written += int(end - start)
            del data
            return written
    raise ValueError("unsupported LMP sample layout")


def _export_adev_csv(path: Path, metadata: dict[str, Any], count: int, output_path: Path) -> int:
    result = _calculate_adev(path, metadata, count, max_samples=None)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        layout = metadata["sample_layout"]
        adev_heading = str(layout["adev_semantic"]).strip()
        if not adev_heading:
            raise ValueError("LMP sample layout requires an ADEV semantic")
        writer.writerow(["tau_s", adev_heading, "m", "pairs"])
        writer.writerows(zip(result.tau_s.tolist(), result.adev.tolist(), result.m.tolist(), result.pairs.tolist()))
    return int(result.tau_s.size)


def _preview_indices(count: int, max_points: int) -> np.ndarray:
    count = int(count)
    max_points = max(1, int(max_points))
    if count <= max_points:
        return np.arange(count, dtype=np.int64)
    return np.unique(np.linspace(0, count - 1, max_points).astype(np.int64))


def _adev_points(result: AllanResult) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for tau, adev in zip(result.tau_s.tolist(), result.adev.tolist()):
        if tau > 0 and adev > 0:
            points.append({"x": float(tau), "y": float(adev)})
    return points


def _adev_unit(metadata: dict[str, Any]) -> str:
    if metadata["app_type"] == "ufc" and metadata["settings"]["divide_adev_by_optical_frequency"]:
        return "ADEV"
    unit = metadata.get("unit", "")
    return f"ADEV ({unit})" if unit else "ADEV"


__all__ = [
    "HEADER_SIZE",
    "LmpWriter",
    "MAGIC",
    "PAYLOAD_OFFSET",
    "SCALAR_RECORD_DTYPE",
    "UFC_SAMPLE_DTYPE",
    "delete_library_item",
    "export_library_series",
    "library_item_preview",
    "library_waveform_preview",
    "list_library_files",
    "read_metadata",
    "rename_library_item",
    "sample_count_from_size",
]
