from __future__ import annotations


class PowerMeterError(RuntimeError):
    """Raised when a power-meter driver or instrument operation fails."""


class PowerMeterDriverUnavailable(PowerMeterError):
    """Raised when the vendor runtime cannot be loaded."""

    def __init__(self, message: str, *, details: str) -> None:
        super().__init__(message)
        self.details = details


__all__ = [
    "PowerMeterDriverUnavailable",
    "PowerMeterError",
]
