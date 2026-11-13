"""Allan deviation helpers for frequency-counter data."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from pathlib import Path

import numpy as np


DEFAULT_OPTICAL_FREQUENCY_HZ = 3.52e14


@dataclass(frozen=True)
class AllanResult:
    tau_s: np.ndarray
    adev: np.ndarray
    m: np.ndarray
    pairs: np.ndarray


def log_spaced_m_values(sample_count: int, points_per_decade: int = 8) -> np.ndarray:
    """Return useful averaging factors for non-overlapping ADEV."""

    if sample_count < 4:
        return np.array([], dtype=np.int64)

    max_m = sample_count // 2
    if max_m < 1:
        return np.array([], dtype=np.int64)

    decades = np.log10(max_m)
    point_count = max(1, int(np.ceil(decades * points_per_decade)) + 1)
    m_values = np.unique(np.logspace(0, decades, point_count).astype(np.int64))
    return m_values[m_values >= 1]


def default_m_values(sample_count: int, sample_rate_hz: float, points_per_decade: int = 8) -> np.ndarray:
    """Return log-spaced averaging factors plus an exact 1 s point when possible."""

    m_values = log_spaced_m_values(sample_count, points_per_decade=points_per_decade)
    one_second_m = int(round(float(sample_rate_hz)))
    if one_second_m >= 1 and int(sample_count) // one_second_m >= 2:
        m_values = np.append(m_values, one_second_m)
    return np.unique(m_values[m_values >= 1])


def non_overlapping_adev(
    fractional_values: np.ndarray | list[float],
    sample_rate_hz: float,
    m_values: np.ndarray | list[int] | None = None,
    segment_starts: list[int] | tuple[int, ...] | None = None,
) -> AllanResult:
    """Compute non-overlapping Allan deviation for fractional frequency data."""

    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")

    y = np.asarray(fractional_values, dtype=np.float64)
    if segment_starts is None:
        y = y[np.isfinite(y)]
    return _array_adev(y, sample_rate_hz, m_values, segment_starts=segment_starts)


def _array_adev(data, sample_rate_hz, m_values, *, segment_starts=None,
                scale=1.0, max_chunk_samples=2_000_000) -> AllanResult:
    y = data
    if y.size < 4:
        empty_float = np.array([], dtype=np.float64)
        empty_int = np.array([], dtype=np.int64)
        return AllanResult(empty_float, empty_float, empty_int, empty_int)

    if m_values is None:
        m_arr = default_m_values(y.size, sample_rate_hz)
    else:
        m_arr = np.asarray(m_values, dtype=np.int64)
        m_arr = np.unique(m_arr[m_arr >= 1])

    taus: list[float] = []
    adevs: list[float] = []
    used_m: list[int] = []
    pairs: list[int] = []
    edges = sorted({0, y.size, *(int(s) for s in (segment_starts or ()) if 0 < int(s) < y.size)})

    for m in m_arr:
        m = int(m)
        sumsq = 0.0
        pair_count = 0
        for segment_start, segment_end in zip(edges, edges[1:]):
            block_count = (segment_end - segment_start) // m
            blocks_per_chunk = max(1, max_chunk_samples // m)
            previous_mean = 0.0
            previous_valid = False
            for block_start in range(0, block_count, blocks_per_chunk):
                this_blocks = min(blocks_per_chunk, block_count - block_start)
                start = segment_start + block_start * m
                means = np.asarray(y[start:start + this_blocks * m]).reshape(this_blocks, m).mean(axis=1) * scale
                finite = np.isfinite(means)
                if previous_valid and finite[0]:
                    diff = float(means[0] - previous_mean)
                    sumsq += diff * diff
                    pair_count += 1
                diffs = np.diff(means)[finite[1:] & finite[:-1]]
                sumsq += float(np.dot(diffs, diffs))
                pair_count += int(diffs.size)
                previous_mean = float(means[-1])
                previous_valid = bool(finite[-1])
        if pair_count == 0:
            continue

        adev = np.sqrt(0.5 * sumsq / pair_count)
        taus.append(float(m) / float(sample_rate_hz))
        adevs.append(float(adev))
        used_m.append(int(m))
        pairs.append(pair_count)

    return AllanResult(
        tau_s=np.asarray(taus, dtype=np.float64),
        adev=np.asarray(adevs, dtype=np.float64),
        m=np.asarray(used_m, dtype=np.int64),
        pairs=np.asarray(pairs, dtype=np.int64),
    )


def frequency_adev(
    frequency_hz: np.ndarray | list[float],
    sample_rate_hz: float,
    optical_frequency_hz: float = DEFAULT_OPTICAL_FREQUENCY_HZ,
    m_values: np.ndarray | list[int] | None = None,
    divide_by_optical_frequency: bool = True,
    divide_by_sqrt2: bool = True,
    segment_starts: list[int] | tuple[int, ...] | None = None,
) -> AllanResult:
    """Convert frequency readings and compute the requested fractional ADEV."""

    y = np.asarray(frequency_hz, dtype=np.float64)
    scale = 1.0
    if divide_by_optical_frequency:
        scale /= float(optical_frequency_hz)
    if divide_by_sqrt2:
        scale /= sqrt(2.0)
    y = y * scale
    return non_overlapping_adev(y, sample_rate_hz, m_values, segment_starts=segment_starts)


def frequency_file_adev(
    frequency_path: Path,
    sample_count: int,
    sample_rate_hz: float,
    optical_frequency_hz: float = DEFAULT_OPTICAL_FREQUENCY_HZ,
    m_values: np.ndarray | list[int] | None = None,
    dtype: np.dtype = np.dtype("<f8"),
    max_chunk_samples: int = 2_000_000,
    divide_by_optical_frequency: bool = True,
    divide_by_sqrt2: bool = True,
    offset: int = 0,
    segment_starts: list[int] | tuple[int, ...] | None = None,
) -> AllanResult:
    """Compute non-overlapping ADEV from a raw frequency file with bounded RAM."""

    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if divide_by_optical_frequency and optical_frequency_hz <= 0:
        raise ValueError("optical_frequency_hz must be positive")
    if sample_count < 4:
        empty_float = np.array([], dtype=np.float64)
        empty_int = np.array([], dtype=np.int64)
        return AllanResult(empty_float, empty_float, empty_int, empty_int)

    data = np.memmap(
        Path(frequency_path),
        dtype=dtype,
        mode="r",
        offset=int(offset),
        shape=(int(sample_count),),
    )
    scale = 1.0
    if divide_by_optical_frequency:
        scale /= float(optical_frequency_hz)
    if divide_by_sqrt2:
        scale /= sqrt(2.0)
    try:
        return _array_adev(
            data, sample_rate_hz, m_values, segment_starts=segment_starts,
            scale=scale, max_chunk_samples=max(1, int(max_chunk_samples)),
        )
    finally:
        del data
