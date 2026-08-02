"""Shared pytest fixtures for the natural-trading test suite."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pytest


class StubAstroSource:
    """Test double for AstroSource — driven by explicit lists of instants per event
    type, so tests can construct exact before/after/boundary scenarios without any
    real astronomical computation or network access."""

    def __init__(
        self,
        winter_solstices: Sequence[datetime] = (),
        summer_solstices: Sequence[datetime] = (),
        new_moons: Sequence[datetime] = (),
        first_quarters: Sequence[datetime] = (),
        full_moons: Sequence[datetime] = (),
        last_quarters: Sequence[datetime] = (),
    ) -> None:
        # Local import keeps conftest import-safe even before source modules exist.
        from natural_trading.astro.base import MoonPhase, SolsticeKind

        self._events: dict[object, list[datetime]] = {
            SolsticeKind.WINTER: sorted(winter_solstices),
            SolsticeKind.SUMMER: sorted(summer_solstices),
            MoonPhase.NEW: sorted(new_moons),
            MoonPhase.FIRST_QUARTER: sorted(first_quarters),
            MoonPhase.FULL: sorted(full_moons),
            MoonPhase.LAST_QUARTER: sorted(last_quarters),
        }

    def _at_or_before(self, key: object, instant: datetime) -> datetime:
        candidates = [d for d in self._events[key] if d <= instant]
        if not candidates:
            raise ValueError(f"No {key} at or before {instant}")
        return max(candidates)

    def _after(self, key: object, instant: datetime) -> datetime:
        candidates = [d for d in self._events[key] if d > instant]
        if not candidates:
            raise ValueError(f"No {key} after {instant}")
        return min(candidates)

    def solstice_at_or_before(self, instant: datetime, kind: object) -> datetime:
        return self._at_or_before(kind, instant)

    def solstice_after(self, instant: datetime, kind: object) -> datetime:
        return self._after(kind, instant)

    def moon_phase_at_or_before(self, instant: datetime, phase: object) -> datetime:
        return self._at_or_before(phase, instant)

    def moon_phase_after(self, instant: datetime, phase: object) -> datetime:
        return self._after(phase, instant)


@pytest.fixture
def stub_astro_source() -> type[StubAstroSource]:
    return StubAstroSource
