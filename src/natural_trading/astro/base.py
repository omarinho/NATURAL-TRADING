"""Abstraction over a source of astronomical event instants.

Two backends implement `AstroSource`: `UsnoSource` (primary, USNO Astronomical
Applications API) and `EphemSource` (offline fallback, the local `ephem` library).
`CombinedAstroSource` (astro/combined.py) wires the two together with fallback-on-error
semantics. See plan.json's astro_source_decision for the rationale.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol


class SolsticeKind(StrEnum):
    WINTER = "winter"
    SUMMER = "summer"


class MoonPhase(StrEnum):
    NEW = "new"
    FIRST_QUARTER = "first_quarter"
    FULL = "full"
    LAST_QUARTER = "last_quarter"


class AstroSource(Protocol):
    def solstice_at_or_before(self, instant: datetime, kind: SolsticeKind) -> datetime:
        """The most recent solstice of `kind` at or before `instant`."""
        ...

    def solstice_after(self, instant: datetime, kind: SolsticeKind) -> datetime:
        """The next solstice of `kind` strictly after `instant`."""
        ...

    def moon_phase_at_or_before(self, instant: datetime, phase: MoonPhase) -> datetime:
        """The most recent occurrence of `phase` at or before `instant`."""
        ...

    def moon_phase_after(self, instant: datetime, phase: MoonPhase) -> datetime:
        """The next occurrence of `phase` strictly after `instant`."""
        ...
