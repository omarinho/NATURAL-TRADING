"""REQ-004/REQ-005/REQ-006 pipeline assembly: computes a candidate symbol's X/Y/Z/W/V
lunar-phase instants from the astro source, fetches its raw IBKR daily bars once, and
resolves them into a screening.llm_screen.PhasePrices via resolver.py's
resolve_phase_price_for_instant / resolve_v_price_for_instant — the piece tying the
astro, pricing, and screening modules together for a single symbol. X's instant is the
New Moon strictly before `new_moon_instant`; Y/Z/W are the following First
Quarter/Full Moon/Last Quarter after X (ports preliminary/find_lunar_stocks.py's
compute_phase_dates from raw ephem calls to the AstroSource protocol).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from natural_trading.astro.base import AstroSource, MoonPhase
from natural_trading.config import Coordinates
from natural_trading.pricing.resolver import (
    DailyBar,
    resolve_phase_price_for_instant,
    resolve_v_price_for_instant,
)
from natural_trading.pricing.session import SessionState
from natural_trading.screening.llm_screen import PhasePrices


class PriceClient(Protocol):
    def fetch_daily_bars(self, symbol: str) -> list[DailyBar]: ...

    def fetch_live_price(self, symbol: str) -> float: ...


@dataclass(frozen=True)
class PhaseInstants:
    x: datetime  # former New Moon
    y: datetime  # following First Quarter
    z: datetime  # following Full Moon
    w: datetime  # following Last Quarter


def compute_phase_instants(new_moon_instant: datetime, astro: AstroSource) -> PhaseInstants:
    """X is the New Moon strictly before `new_moon_instant` — querying
    `moon_phase_at_or_before` on `new_moon_instant` itself would return
    `new_moon_instant` right back (it IS a New Moon), so the query instant is nudged
    back one day first, safely inside the ~29.5-day gap to the prior New Moon."""
    x = astro.moon_phase_at_or_before(new_moon_instant - timedelta(days=1), MoonPhase.NEW)
    y = astro.moon_phase_after(x, MoonPhase.FIRST_QUARTER)
    z = astro.moon_phase_after(x, MoonPhase.FULL)
    w = astro.moon_phase_after(x, MoonPhase.LAST_QUARTER)
    return PhaseInstants(x=x, y=y, z=z, w=w)


def resolve_symbol_phase_prices(
    symbol: str,
    new_moon_instant: datetime,
    astro: AstroSource,
    coordinates: Coordinates,
    price_client: PriceClient,
    session_state: SessionState,
) -> PhasePrices | None:
    """Returns None if X/Y/Z/W has no resolvable close (discarded, mirroring
    preliminary/find_lunar_stocks.py's fetch_prices treatment of missing bars) —
    never raises for an ordinary missing-data case."""
    instants = compute_phase_instants(new_moon_instant, astro)
    bars = price_client.fetch_daily_bars(symbol)

    x = resolve_phase_price_for_instant(bars, instants.x, coordinates)
    y = resolve_phase_price_for_instant(bars, instants.y, coordinates)
    z = resolve_phase_price_for_instant(bars, instants.z, coordinates)
    w = resolve_phase_price_for_instant(bars, instants.w, coordinates)
    if x is None or y is None or z is None or w is None:
        return None

    v = resolve_v_price_for_instant(
        bars,
        new_moon_instant,
        coordinates,
        session_state,
        lambda: price_client.fetch_live_price(symbol),
    )
    return PhasePrices(x=x, y=y, z=z, w=w, v=v)
