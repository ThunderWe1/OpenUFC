from __future__ import annotations

from dataclasses import dataclass


class InstrumentError(RuntimeError):
    """Raised when an instrument operation fails."""


@dataclass(slots=True, frozen=True)
class InstrumentIdentity:
    manufacturer: str
    model: str
    serial: str
    firmware: str
    raw: str
