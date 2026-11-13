from __future__ import annotations


class WavelengthMeterError(RuntimeError):
    """Raised when a wavelength-meter connection or reading fails."""


__all__ = ["WavelengthMeterError"]
