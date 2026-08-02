"""Covers pricing/pipeline.py — the assembly step wiring astro phase-instant
computation, a single raw-bars fetch, and resolver.py's resolve_*_for_instant
functions into a screening-ready PhasePrices for one candidate symbol."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from natural_trading.astro.base import MoonPhase
from natural_trading.config import Coordinates
from natural_trading.pricing.pipeline import compute_phase_instants, resolve_symbol_phase_prices
from natural_trading.pricing.resolver import DailyBar
from natural_trading.pricing.session import SessionState
from natural_trading.screening.llm_screen import PhasePrices

COORDINATES = Coordinates(latitude=0.0, longitude=0.0)
NEW_MOON = datetime(2024, 6, 6, 12, 0, tzinfo=UTC)


def _fake_astro() -> MagicMock:
    astro = MagicMock()
    astro.moon_phase_at_or_before.return_value = datetime(2024, 5, 7, tzinfo=UTC)  # X
    astro.moon_phase_after.side_effect = lambda instant, phase: {
        MoonPhase.FIRST_QUARTER: datetime(2024, 5, 15, tzinfo=UTC),
        MoonPhase.FULL: datetime(2024, 5, 23, tzinfo=UTC),
        MoonPhase.LAST_QUARTER: datetime(2024, 5, 30, tzinfo=UTC),
    }[phase]
    return astro


# ─── compute_phase_instants ─────────────────────────────────────────────────────────


def test_x_queried_strictly_before_the_new_moon_instant() -> None:
    astro = _fake_astro()
    compute_phase_instants(NEW_MOON, astro)

    (queried_instant, phase), _ = astro.moon_phase_at_or_before.call_args
    assert queried_instant < NEW_MOON
    assert phase is MoonPhase.NEW


def test_y_z_w_are_the_next_occurrence_after_x() -> None:
    astro = _fake_astro()
    x_instant = datetime(2024, 5, 7, tzinfo=UTC)

    result = compute_phase_instants(NEW_MOON, astro)

    assert result.x == x_instant
    calls = astro.moon_phase_after.call_args_list
    assert all(call.args[0] == x_instant for call in calls)
    queried_phases = {call.args[1] for call in calls}
    assert queried_phases == {MoonPhase.FIRST_QUARTER, MoonPhase.FULL, MoonPhase.LAST_QUARTER}


# ─── resolve_symbol_phase_prices ────────────────────────────────────────────────────

_BARS = [
    DailyBar(trading_date=datetime(2024, 5, 7, tzinfo=UTC).date(), close=100.0),
    DailyBar(trading_date=datetime(2024, 5, 15, tzinfo=UTC).date(), close=110.0),
    DailyBar(trading_date=datetime(2024, 5, 23, tzinfo=UTC).date(), close=120.0),
    DailyBar(trading_date=datetime(2024, 5, 30, tzinfo=UTC).date(), close=115.0),
    DailyBar(trading_date=datetime(2024, 6, 6, tzinfo=UTC).date(), close=112.0),
]


def _fake_price_client(bars: list[DailyBar] = _BARS, live_price: float = 999.0) -> MagicMock:
    client = MagicMock()
    client.fetch_daily_bars.return_value = bars
    client.fetch_live_price.return_value = live_price
    return client


def test_returns_phase_prices_when_all_bars_resolve() -> None:
    astro = _fake_astro()
    client = _fake_price_client()

    result = resolve_symbol_phase_prices(
        "AAPL", NEW_MOON, astro, COORDINATES, client, SessionState.CLOSED_AFTER_SESSION
    )

    assert result == PhasePrices(x=100.0, y=110.0, z=120.0, w=115.0, v=112.0)


def test_fetches_bars_exactly_once_for_all_five_points() -> None:
    astro = _fake_astro()
    client = _fake_price_client()

    resolve_symbol_phase_prices(
        "AAPL", NEW_MOON, astro, COORDINATES, client, SessionState.CLOSED_AFTER_SESSION
    )

    client.fetch_daily_bars.assert_called_once_with("AAPL")


def test_returns_none_when_a_phase_price_is_unresolvable() -> None:
    astro = _fake_astro()
    client = _fake_price_client(bars=[])  # no bars at all -> every phase price is None

    result = resolve_symbol_phase_prices(
        "AAPL", NEW_MOON, astro, COORDINATES, client, SessionState.CLOSED_AFTER_SESSION
    )

    assert result is None


def test_v_uses_live_price_when_session_open() -> None:
    astro = _fake_astro()
    bars_without_today = _BARS[:-1]
    client = _fake_price_client(bars=bars_without_today, live_price=118.5)

    result = resolve_symbol_phase_prices(
        "AAPL", NEW_MOON, astro, COORDINATES, client, SessionState.OPEN
    )

    assert result is not None
    assert result.v == 118.5
    client.fetch_live_price.assert_called_once_with("AAPL")


def test_v_does_not_fetch_live_price_when_session_closed() -> None:
    astro = _fake_astro()
    client = _fake_price_client()

    resolve_symbol_phase_prices(
        "AAPL", NEW_MOON, astro, COORDINATES, client, SessionState.CLOSED_AFTER_SESSION
    )

    client.fetch_live_price.assert_not_called()
