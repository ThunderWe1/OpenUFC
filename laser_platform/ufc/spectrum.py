"""One-sided frequency-noise power spectral density using Welch averaging."""

from __future__ import annotations

import numpy as np


def frequency_noise_psd(
    values, sample_rate_hz: float, segment_length: int = 1024,
    window: str = "hann", overlap_percent: int = 50, segment_starts=(),
) -> dict:
    """Average complete, contiguous windows; remove each window's mean.

    Density scaling is |FFT|² / (fs * sum(window²)), with positive-frequency
    bins doubled except Nyquist. Values remain absolute frequency in Hz.
    """
    rate = float(sample_rate_hz)
    if not np.isfinite(rate) or rate <= 0:
        raise ValueError("Sample rate must be finite and positive")
    length = int(segment_length)
    if length != segment_length or length < 16 or length > 16384 or length & (length - 1):
        raise ValueError("Segment length must be a power of two from 16 to 16384")
    if window not in {"hann", "hamming", "boxcar"}:
        raise ValueError("Window must be hann, hamming, or boxcar")
    if overlap_percent not in {0, 50, 75}:
        raise ValueError("Overlap must be 0, 50, or 75 percent")
    samples = np.asarray(values, dtype=np.float64)
    if samples.ndim != 1:
        raise ValueError("Frequency measurements must be one-dimensional")
    phase = 2 * np.pi * np.arange(length) / length
    weights = (0.5 - 0.5 * np.cos(phase) if window == "hann" else
               0.54 - 0.46 * np.cos(phase) if window == "hamming" else np.ones(length))
    step = length - length * overlap_percent // 100
    boundaries = sorted({0, samples.size, *(int(i) for i in segment_starts if 0 < i < samples.size)})
    power = np.zeros(length // 2 + 1)
    averages = 0
    for start, end in zip(boundaries, boundaries[1:]):
        for position in range(start, end - length + 1, step):
            block = samples[position:position + length]
            if not np.all(np.isfinite(block)):
                continue
            # Subtract the carrier before the mean to retain small fluctuations.
            centered = block - block[0]
            centered -= np.mean(centered)
            transform = np.fft.rfft(centered * weights)
            power += np.abs(transform) ** 2
            averages += 1
    points = []
    if averages:
        power /= averages * rate * np.sum(weights ** 2)
        power[1:-1] *= 2
        frequencies = np.fft.rfftfreq(length, 1 / rate)
        # DC is removed intentionally; zero noise bins remain valid on linear Y.
        points = [{"x": float(x), "y": float(y)} for x, y in zip(frequencies[1:], power[1:])]
    return {
        "points": points, "unit": "Hz²/Hz", "averages": averages,
        "sample_count": int(samples.size), "sample_rate_hz": rate,
        "segment_length": length, "resolution_hz": rate / length,
    }
