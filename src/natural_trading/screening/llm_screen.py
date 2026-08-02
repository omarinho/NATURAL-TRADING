"""REQ-003: the lunar-stock pattern check — a pure, deterministic comparison of the
five phase-day close prices against the active season's required ordering. REQ-017:
zero qualifying candidates is a valid outcome — no exception is raised.
"""

from __future__ import annotations

from dataclasses import dataclass

from natural_trading.astro.season import Season


@dataclass(frozen=True)
class PhasePrices:
    x: float  # close on the former New Moon
    y: float  # close on the following First Quarter
    z: float  # close on the following Full Moon
    w: float  # close on the following Last Quarter
    v: float  # price on today's New Moon (the trade-open day)


def screen_candidate(prices: PhasePrices, season: Season) -> bool:
    """BUY season: X<Y<Z, then Z>W, then W>V. SELL season: X>Y>Z, then Z<W, then W<V."""
    if season is Season.BUY:
        return prices.x < prices.y < prices.z and prices.z > prices.w > prices.v
    return prices.x > prices.y > prices.z and prices.z < prices.w < prices.v


def screen_candidates(candidates: dict[str, PhasePrices], season: Season) -> list[str]:
    """REQ-017: an empty result is a valid, non-error outcome."""
    return [symbol for symbol, prices in candidates.items() if screen_candidate(prices, season)]
