"""REQ-001: season detection uses the exact solstice instant, never a calendar date.
REQ-002: solstice-straddling lunar cycles are skipped entirely.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from natural_trading.astro.base import AstroSource, SolsticeKind


class Season(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


def determine_season(instant: datetime, astro: AstroSource) -> Season:
    """BUY season: Winter Solstice -> Summer Solstice. SELL season: Summer Solstice ->
    Winter Solstice. Whichever solstice most recently occurred at-or-before `instant`
    determines the season, so a boundary instant transitions immediately."""
    last_winter = astro.solstice_at_or_before(instant, SolsticeKind.WINTER)
    last_summer = astro.solstice_at_or_before(instant, SolsticeKind.SUMMER)
    return Season.BUY if last_winter > last_summer else Season.SELL


def is_solstice_straddling_cycle(
    new_moon_instant: datetime, full_moon_instant: datetime, astro: AstroSource
) -> bool:
    """True when a lunar cycle's New Moon and its following Full Moon fall in different
    seasons — such a cycle is skipped entirely (no opening order at the New Moon)."""
    return determine_season(new_moon_instant, astro) != determine_season(full_moon_instant, astro)
