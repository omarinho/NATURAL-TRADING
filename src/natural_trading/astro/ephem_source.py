"""Offline fallback astro source backed by the local `ephem` library — used when the
USNO API is unreachable so a transient outage can't cause a missed New Moon/Full Moon
trigger (see plan.json's astro_source_decision)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import ephem

from natural_trading.astro.base import MoonPhase, SolsticeKind
from natural_trading.config import Coordinates

_MOON_PHASE_PREVIOUS: dict[MoonPhase, Callable[[object], ephem.Date]] = {
    MoonPhase.NEW: ephem.previous_new_moon,
    MoonPhase.FIRST_QUARTER: ephem.previous_first_quarter_moon,
    MoonPhase.FULL: ephem.previous_full_moon,
    MoonPhase.LAST_QUARTER: ephem.previous_last_quarter_moon,
}
_MOON_PHASE_NEXT: dict[MoonPhase, Callable[[object], ephem.Date]] = {
    MoonPhase.NEW: ephem.next_new_moon,
    MoonPhase.FIRST_QUARTER: ephem.next_first_quarter_moon,
    MoonPhase.FULL: ephem.next_full_moon,
    MoonPhase.LAST_QUARTER: ephem.next_last_quarter_moon,
}
_SOLSTICE_PREVIOUS: dict[SolsticeKind, Callable[[object], ephem.Date]] = {
    SolsticeKind.WINTER: ephem.previous_winter_solstice,
    SolsticeKind.SUMMER: ephem.previous_summer_solstice,
}
_SOLSTICE_NEXT: dict[SolsticeKind, Callable[[object], ephem.Date]] = {
    SolsticeKind.WINTER: ephem.next_winter_solstice,
    SolsticeKind.SUMMER: ephem.next_summer_solstice,
}


def _to_ephem_date(instant: datetime) -> ephem.Date:
    if instant.tzinfo is not None:
        instant = instant.astimezone(UTC).replace(tzinfo=None)
    return ephem.Date(instant)


def _to_datetime(value: ephem.Date) -> datetime:
    # ephem ships no type stubs, so `value.datetime()` is seen as Any; pin it to the
    # declared `datetime` type explicitly rather than silently returning Any.
    naive: datetime = value.datetime()
    return naive.replace(tzinfo=UTC)


class EphemSource:
    """AstroSource backend using the offline `ephem` library — no network required."""

    def __init__(self, coordinates: Coordinates | None = None) -> None:
        # REQ-018: the module-level ephem functions used below (previous_new_moon,
        # previous_winter_solstice, etc. — see _MOON_PHASE_PREVIOUS/_SOLSTICE_PREVIOUS
        # above) take an instant only, no observer location; New Moon and solstice
        # instants are geocentric, so `coordinates` does not alter the instant
        # computed here. It is still accepted and stored so the configured location
        # genuinely flows end-to-end from main.py through to this backend. See
        # natural_trading.pricing.resolver.local_date_of for the local "day of"
        # boundary calculation where coordinates DO change observable output.
        self.coordinates = coordinates

    def solstice_at_or_before(self, instant: datetime, kind: SolsticeKind) -> datetime:
        ephem_instant = _to_ephem_date(instant)
        candidate = _SOLSTICE_PREVIOUS[kind](ephem.Date(ephem_instant) + 1)
        if candidate > ephem_instant:
            candidate = _SOLSTICE_PREVIOUS[kind](ephem_instant)
        return _to_datetime(candidate)

    def solstice_after(self, instant: datetime, kind: SolsticeKind) -> datetime:
        return _to_datetime(_SOLSTICE_NEXT[kind](_to_ephem_date(instant)))

    def moon_phase_at_or_before(self, instant: datetime, phase: MoonPhase) -> datetime:
        ephem_instant = _to_ephem_date(instant)
        candidate = _MOON_PHASE_PREVIOUS[phase](ephem.Date(ephem_instant) + 1)
        if candidate > ephem_instant:
            candidate = _MOON_PHASE_PREVIOUS[phase](ephem_instant)
        return _to_datetime(candidate)

    def moon_phase_after(self, instant: datetime, phase: MoonPhase) -> datetime:
        return _to_datetime(_MOON_PHASE_NEXT[phase](_to_ephem_date(instant)))
