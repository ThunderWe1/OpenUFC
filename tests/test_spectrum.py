import numpy as np
import pytest

from laser_platform.ufc.spectrum import frequency_noise_psd


@pytest.mark.parametrize("window", ["hann", "hamming", "boxcar"])
@pytest.mark.parametrize("overlap", [0, 50, 75])
def test_tone_frequency_and_integrated_noise_power(window, overlap):
    samples = 10_000_000 + 3 * np.sin(2 * np.pi * 125 * np.arange(4096) / 1024)
    result = frequency_noise_psd(samples, 1024, 1024, window, overlap)
    assert max(result["points"], key=lambda point: point["y"])["x"] == 125
    assert sum(point["y"] for point in result["points"]) * result["resolution_hz"] == pytest.approx(4.5, rel=1e-9)
    assert result["averages"] == 1 + (4096 - 1024) // (1024 * (100 - overlap) // 100)
    assert result["points"][-1]["x"] == 512
    assert result["points"][0]["x"] == 1


def test_nyquist_is_not_doubled_and_white_noise_density_has_correct_units():
    result = frequency_noise_psd(2 * (-1.) ** np.arange(1024), 1024, window="boxcar")
    assert sum(point["y"] for point in result["points"]) == pytest.approx(4)
    noise = np.random.default_rng(42).normal(0, 3, 65536)
    result = frequency_noise_psd(noise, 1000)
    density = np.mean([point["y"] for point in result["points"][:-1]])
    assert density == pytest.approx(2 * 9 / 1000, rel=0.04)


def test_boundaries_and_invalid_samples_do_not_create_noise():
    samples = np.r_[np.full(96, 10_000_000.), np.full(96, 20_000_000.)]
    result = frequency_noise_psd(samples, 1000, 64, segment_starts=[96])
    assert result["averages"] == 4
    assert all(point["y"] == 0 for point in result["points"])
    samples[3] = np.nan
    result = frequency_noise_psd(samples, 1000, 64, segment_starts=[96])
    assert result["averages"] == 3
    assert all(point["y"] == 0 for point in result["points"])
    assert frequency_noise_psd(samples, 1000, 128, segment_starts=[96])["points"] == []
    assert frequency_noise_psd([], 1000)["averages"] == 0


@pytest.mark.parametrize("parameters", [
    {"sample_rate_hz": 0}, {"sample_rate_hz": float("nan")},
    {"segment_length": 17}, {"segment_length": 32768},
    {"window": "unknown"}, {"overlap_percent": 100},
])
def test_invalid_parameters_are_rejected(parameters):
    with pytest.raises(ValueError):
        frequency_noise_psd([], **{"sample_rate_hz": 1000, **parameters})
