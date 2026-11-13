from __future__ import annotations

import copy
import json
import os
import threading
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from laser_platform.wlm.models import (
    DEFAULT_WLM_CONNECTION_MODE,
    WLM_USB_RESOURCE,
    WavelengthMeterConfig,
)


DEFAULT_INSTRUMENT_SETTINGS: dict[str, dict[str, Any]] = {
    "ufc": {
        "resource": "",
        "channel": 1,
        "sample_rate_hz": 1000,
        "wavelength_nm": 851.683,
        "divide_adev_by_optical_frequency": True,
        "divide_adev_by_sqrt2": True,
        "analysis_tab": "adev",
        "fn_segment_length": 1024,
        "fn_window": "hann",
        "fn_overlap_percent": 50,
        "fn_log_x": True,
        "fn_log_y": True,
    },
    "dmm": {
        "resource": "",
        "measurement_function": "VOLT:DC",
        "autorange": True,
        "range_value": 10.0,
        "nplc": 1.0,
    },
    "opm": {
        "resource": "",
        "wavelength_nm": 852.0,
        "display_unit": "mW",
        "autorange": True,
        "manual_range_w": 0.01,
        "channel": 1,
    },
    "wlm": {
        "connection_mode": DEFAULT_WLM_CONNECTION_MODE,
        "resource": WLM_USB_RESOURCE,
        "ethernet_resource": "",
    },
}


def _default_instruments() -> list[dict[str, Any]]:
    return [
        {
            "id": "ufc-default",
            "type": "ufc",
            "settings": copy.deepcopy(DEFAULT_INSTRUMENT_SETTINGS["ufc"]),
        },
        {
            "id": "dmm-default",
            "type": "dmm",
            "settings": copy.deepcopy(DEFAULT_INSTRUMENT_SETTINGS["dmm"]),
        },
    ]


DEFAULT_CONFIG: dict[str, Any] = {
    "platform": {
        "library_dir": "runs",
        "color_mode": "auto",
    },
    "instruments": _default_instruments(),
}


def default_config_path() -> Path:
    return Path.cwd() / "config.json"


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def default_instrument_settings(kind: str) -> dict[str, Any]:
    try:
        return copy.deepcopy(DEFAULT_INSTRUMENT_SETTINGS[kind])
    except KeyError as exc:
        raise ValueError(f"unsupported instrument type: {kind}") from exc


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    platform = config.get("platform")
    if not isinstance(platform, dict):
        platform = {}
    library_dir = str(platform.get("library_dir") or DEFAULT_CONFIG["platform"]["library_dir"])
    color_mode = platform.get("color_mode", "auto")
    if color_mode not in ("auto", "light", "dark"):
        raise ValueError("color mode must be auto, light, or dark")
    return {
        "platform": {
            "library_dir": library_dir,
            "color_mode": color_mode,
        },
        "instruments": _normalize_instruments(config.get("instruments")),
    }


def _new_instrument_id(kind: str) -> str:
    return f"{kind}-{uuid4().hex[:8]}"


def _normalize_instruments(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return _default_instruments()
    if not raw:
        return []

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type", "")).lower()
        if kind not in {"ufc", "dmm", "opm", "wlm"}:
            raise ValueError(f"unsupported instrument type: {kind or '<missing>'}")
        instance_id = str(item.get("id", "")).strip() or _new_instrument_id(kind)
        if instance_id in seen:
            instance_id = _new_instrument_id(kind)
        seen.add(instance_id)
        base_settings = default_instrument_settings(kind)
        settings = item.get("settings", {})
        if isinstance(settings, dict):
            current_settings = {
                key: value
                for key, value in settings.items()
                if key in base_settings
            }
            base_settings = merge_dicts(base_settings, current_settings)
        if kind == "wlm":
            base_settings = WavelengthMeterConfig.from_payload(base_settings).as_dict()
        normalized_item = {"id": instance_id, "type": kind, "settings": base_settings}
        display_name = str(item.get("display_name", "") or "").strip()
        if display_name:
            normalized_item["display_name"] = display_name
        normalized.append(normalized_item)
    return normalized


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                normalized = _normalize_config(copy.deepcopy(DEFAULT_CONFIG))
                _write_config_atomically(self.path, normalized)
                return normalized
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return _normalize_config(copy.deepcopy(DEFAULT_CONFIG))
            normalized = _normalize_config(payload)
            if normalized != payload:
                _write_config_atomically(self.path, normalized)
            return normalized

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("config patch must be an object")
        with self._lock:
            current: dict[str, Any] = {}
            if self.path.exists():
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    current = payload
            updated = _normalize_config(merge_dicts(_normalize_config(current), patch))
            _write_config_atomically(self.path, updated)
            return updated


def _write_config_atomically(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


__all__ = [
    "ConfigStore",
    "DEFAULT_CONFIG",
    "default_instrument_settings",
    "merge_dicts",
]
