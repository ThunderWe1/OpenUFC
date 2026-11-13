from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(slots=True, frozen=True)
class StatsSnapshot:
    latest: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    average: float | None = None
    count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RollingStats:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._latest: float | None = None
        self._minimum: float | None = None
        self._maximum: float | None = None
        self._total = 0.0
        self._count = 0

    def update(self, value: float) -> StatsSnapshot:
        value = float(value)
        self._latest = value
        self._minimum = value if self._minimum is None else min(self._minimum, value)
        self._maximum = value if self._maximum is None else max(self._maximum, value)
        self._total += value
        self._count += 1
        return self.snapshot()

    def snapshot(self) -> StatsSnapshot:
        return StatsSnapshot(
            latest=self._latest,
            minimum=self._minimum,
            maximum=self._maximum,
            average=(self._total / self._count) if self._count else None,
            count=self._count,
        )


def elapsed_duration_s(elapsed: np.ndarray) -> float:
    if elapsed.size >= 2:
        return max(0.0, float(elapsed[-1] - elapsed[0]))
    return 0.0


def estimated_sample_rate(elapsed: np.ndarray, default_hz: float) -> float:
    if elapsed.size >= 2:
        duration = elapsed_duration_s(elapsed)
        if duration > 0:
            return max(1e-12, float(elapsed.size - 1) / duration)
    return max(1e-12, float(default_hz))


__all__ = [
    "RollingStats",
    "StatsSnapshot",
    "elapsed_duration_s",
    "estimated_sample_rate",
]
