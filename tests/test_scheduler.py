"""Covers REQ-009 (New Moon trigger creates MARKET opening orders), REQ-010 (Full Moon
trigger creates MARKET closing orders), and REQ-012 (orders submitted immediately at
the exact instant regardless of market hours)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from natural_trading.astro.base import MoonPhase
from natural_trading.orders import OrderAction
from natural_trading.scheduler import (
    ALREADY_PROCESSED_TOLERANCE,
    CATCH_UP_WINDOW,
    most_recent_trigger_instant,
    next_trigger_instant,
    resolve_next_action,
    run_full_moon_cycle,
    run_new_moon_cycle,
    run_new_moon_cycle_live,
)
from tests.conftest import StubAstroSource

UTC = UTC


def _dt(y: int, m: int, d: int, h: int = 0) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


# ─── REQ-009 ────────────────────────────────────────────────────────────────────────


def test_exact_new_moon_in_buy_season_submits_market_buy_orders(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    submitter = MagicMock()
    result = run_new_moon_cycle(
        new_moon_instant=_dt(2024, 3, 10),
        following_full_moon_instant=_dt(2024, 3, 25),
        astro=astro,
        qualifying_symbols=["AAA", "BBB"],
        equity=100_000,
        buying_power=100_000,
        short_sale_buying_power=100_000,
        prices={"AAA": 100.0, "BBB": 100.0},
        submitter=submitter,
    )
    assert result.skipped_straddle is False
    assert len(result.orders_submitted) == 2
    assert all(o.action is OrderAction.BUY for o in result.orders_submitted)
    assert submitter.submit.call_count == 2


def test_exact_new_moon_in_sell_season_submits_market_sell_short_orders(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)], summer_solstices=[_dt(2024, 6, 20)]
    )
    submitter = MagicMock()
    result = run_new_moon_cycle(
        new_moon_instant=_dt(2024, 9, 10),
        following_full_moon_instant=_dt(2024, 9, 25),
        astro=astro,
        qualifying_symbols=["AAA"],
        equity=100_000,
        buying_power=100_000,
        short_sale_buying_power=100_000,
        prices={"AAA": 100.0},
        submitter=submitter,
    )
    assert all(o.action is OrderAction.SELL for o in result.orders_submitted)


def test_solstice_straddling_new_moon_submits_no_opening_orders(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    submitter = MagicMock()
    result = run_new_moon_cycle(
        new_moon_instant=_dt(2024, 6, 1),  # BUY season
        following_full_moon_instant=_dt(2024, 6, 30),  # SELL season -> straddling
        astro=astro,
        qualifying_symbols=["AAA"],
        equity=100_000,
        buying_power=100_000,
        short_sale_buying_power=100_000,
        prices={},  # never consulted — the straddle guard returns before sizing
        submitter=submitter,
    )
    assert result.skipped_straddle is True
    assert result.orders_submitted == []
    submitter.submit.assert_not_called()


def test_symbol_sized_to_zero_shares_is_skipped_not_submitted(
    stub_astro_source: type[StubAstroSource],
) -> None:
    """A sized dollar amount smaller than one share's price floors to 0 shares (e.g. a
    thinly-capitalized account, some candidates high-priced) — IBKR rejects a
    0-quantity order outright, so it must never even be submitted."""
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    submitter = MagicMock()
    result = run_new_moon_cycle(
        new_moon_instant=_dt(2024, 3, 10),
        following_full_moon_instant=_dt(2024, 3, 25),
        astro=astro,
        qualifying_symbols=["AFFORDABLE", "TOO_EXPENSIVE"],
        equity=1_000,  # 20% cap -> $200 per symbol
        buying_power=1_000,
        short_sale_buying_power=1_000,
        prices={"AFFORDABLE": 10.0, "TOO_EXPENSIVE": 500.0},  # $200 // $500 = 0 shares
        submitter=submitter,
    )
    assert {o.symbol for o in result.orders_submitted} == {"AFFORDABLE"}
    submitter.submit.assert_called_once()


def test_next_trigger_computed_from_astro_source_not_fixed_offset(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(new_moons=[_dt(2024, 4, 8)], full_moons=[_dt(2024, 4, 23)])
    instant, phase = next_trigger_instant(_dt(2024, 3, 15), astro)
    assert instant == _dt(2024, 4, 8)
    assert phase is MoonPhase.NEW


# ─── most_recent_trigger_instant / resolve_next_action (cold-start catch-up) ───────


def test_most_recent_trigger_picks_the_newer_of_new_and_full_moon(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(new_moons=[_dt(2024, 4, 8)], full_moons=[_dt(2024, 4, 23)])
    instant, phase = most_recent_trigger_instant(_dt(2024, 4, 25), astro)
    assert instant == _dt(2024, 4, 23)
    assert phase is MoonPhase.FULL


def test_resolve_next_action_catches_up_on_unprocessed_recent_trigger(
    stub_astro_source: type[StubAstroSource],
) -> None:
    """A cold start shortly after the real instant (never processed before) must
    process that trigger, not silently skip to the next one ~14.75 days later."""
    astro = stub_astro_source(
        new_moons=[_dt(2024, 4, 8), _dt(2024, 5, 7)],
        full_moons=[_dt(2024, 3, 24), _dt(2024, 4, 23)],
    )
    now = _dt(2024, 4, 8, 1)  # 1 hour after the New Moon instant, never processed
    instant, phase = resolve_next_action(now, astro, last_processed=None)
    assert instant == _dt(2024, 4, 8)
    assert phase is MoonPhase.NEW


def test_resolve_next_action_catches_up_on_unprocessed_recent_full_moon(
    stub_astro_source: type[StubAstroSource],
) -> None:
    """Mirrors the New Moon catch-up case -- resolve_next_action is phase-agnostic,
    not New-Moon-specific, since a Full Moon close is just as important to not
    silently skip as a New Moon open."""
    astro = stub_astro_source(
        new_moons=[_dt(2024, 4, 8), _dt(2024, 5, 7)],
        full_moons=[_dt(2024, 3, 24), _dt(2024, 4, 23)],
    )
    now = _dt(2024, 4, 23, 1)  # 1 hour after the Full Moon instant, never processed
    instant, phase = resolve_next_action(now, astro, last_processed=None)
    assert instant == _dt(2024, 4, 23)
    assert phase is MoonPhase.FULL


def test_resolve_next_action_does_not_reprocess_an_already_handled_trigger(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        new_moons=[_dt(2024, 4, 8), _dt(2024, 5, 7)],
        full_moons=[_dt(2024, 3, 24), _dt(2024, 4, 23)],
    )
    now = _dt(2024, 4, 8, 1)
    instant, phase = resolve_next_action(now, astro, last_processed=_dt(2024, 4, 8))
    # Already processed the 4/8 New Moon -> falls through to the normal next-trigger
    assert instant == _dt(2024, 4, 23)
    assert phase is MoonPhase.FULL


def test_resolve_next_action_treats_a_close_last_processed_as_the_same_event(
    stub_astro_source: type[StubAstroSource],
) -> None:
    """A restart may recompute the same real event via a different astro backend
    (USNO vs ephem), which can legitimately differ by minutes without being a
    different event -- exact equality would risk resubmitting it."""
    astro = stub_astro_source(
        new_moons=[_dt(2024, 4, 8), _dt(2024, 5, 7)],
        full_moons=[_dt(2024, 3, 24), _dt(2024, 4, 23)],
    )
    now = _dt(2024, 4, 8, 1)
    close_but_not_exact = _dt(2024, 4, 8) + (ALREADY_PROCESSED_TOLERANCE / 2)
    instant, phase = resolve_next_action(now, astro, last_processed=close_but_not_exact)
    assert instant == _dt(2024, 4, 23)
    assert phase is MoonPhase.FULL


def test_resolve_next_action_does_not_catch_up_outside_the_window(
    stub_astro_source: type[StubAstroSource],
) -> None:
    """Well outside CATCH_UP_WINDOW is treated as a genuinely missed cycle, not a
    late cold start -- falls through to the normal next-trigger wait rather than
    processing a stale trigger."""
    astro = stub_astro_source(
        new_moons=[_dt(2024, 4, 8), _dt(2024, 5, 7)],
        full_moons=[_dt(2024, 3, 24), _dt(2024, 4, 23)],
    )
    now = _dt(2024, 4, 8) + CATCH_UP_WINDOW + timedelta(microseconds=1)
    instant, phase = resolve_next_action(now, astro, last_processed=None)
    assert instant == _dt(2024, 4, 23)
    assert phase is MoonPhase.FULL


# ─── REQ-010 ────────────────────────────────────────────────────────────────────────


def test_full_moon_with_open_long_position_submits_market_sell_full_quantity() -> None:
    submitter = MagicMock()
    orders = run_full_moon_cycle({"AAA": 100.0}, submitter)
    assert len(orders) == 1
    assert orders[0].action is OrderAction.SELL
    assert orders[0].quantity == 100.0


def test_full_moon_with_open_short_position_submits_market_buy_to_cover_full_quantity() -> None:
    submitter = MagicMock()
    orders = run_full_moon_cycle({"AAA": -50.0}, submitter)
    assert orders[0].action is OrderAction.BUY
    assert orders[0].quantity == 50.0


def test_all_open_positions_closed_at_full_moon_none_left_open() -> None:
    submitter = MagicMock()
    orders = run_full_moon_cycle({"AAA": 100.0, "BBB": -25.0}, submitter)
    assert {o.symbol for o in orders} == {"AAA", "BBB"}
    assert submitter.submit.call_count == 2


# ─── REQ-012 ────────────────────────────────────────────────────────────────────────


def test_new_moon_instant_at_night_submits_orders_immediately_not_queued(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    submitter = MagicMock()
    run_new_moon_cycle(
        new_moon_instant=_dt(2024, 3, 10, 2),  # 2 AM — market closed
        following_full_moon_instant=_dt(2024, 3, 25, 2),
        astro=astro,
        qualifying_symbols=["AAA"],
        equity=100_000,
        buying_power=100_000,
        short_sale_buying_power=100_000,
        prices={"AAA": 100.0},
        submitter=submitter,
    )
    submitter.submit.assert_called_once()  # submitted within the same call, no queueing


def test_new_moon_on_weekend_submits_orders_immediately(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    submitter = MagicMock()
    saturday = _dt(2024, 3, 9)
    run_new_moon_cycle(
        new_moon_instant=saturday,
        following_full_moon_instant=_dt(2024, 3, 24),
        astro=astro,
        qualifying_symbols=["AAA"],
        equity=100_000,
        buying_power=100_000,
        short_sale_buying_power=100_000,
        prices={"AAA": 100.0},
        submitter=submitter,
    )
    submitter.submit.assert_called_once()


def test_scheduler_module_contains_no_market_session_gating_before_submission() -> None:
    scheduler_src = Path(__file__).resolve().parents[1] / "src" / "natural_trading" / "scheduler.py"
    text = scheduler_src.read_text().lower()
    forbidden = ("market_open", "next_session", "wait_for_open", "is_trading_day")
    for token in forbidden:
        assert token not in text


# ─── REQ-016 ────────────────────────────────────────────────────────────────────────


def test_run_new_moon_cycle_live_fetches_fresh_buying_power_before_submission(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    account = MagicMock()
    account.fetch_buying_power.return_value = 100_000.0
    account.fetch_short_sale_buying_power.return_value = 100_000.0
    submitter = MagicMock()

    result = run_new_moon_cycle_live(
        new_moon_instant=_dt(2024, 3, 10),
        following_full_moon_instant=_dt(2024, 3, 25),
        astro=astro,
        qualifying_symbols=["AAA"],
        equity=100_000,
        prices={"AAA": 100.0},
        account=account,
        submitter=submitter,
    )

    account.fetch_buying_power.assert_called_once()
    submitter.submit.assert_called_once()
    assert result.orders_submitted[0].action is OrderAction.BUY


def test_run_new_moon_cycle_live_uses_short_sale_buying_power_in_sell_season(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)], summer_solstices=[_dt(2024, 6, 20)]
    )
    account = MagicMock()
    account.fetch_buying_power.return_value = 100_000.0
    account.fetch_short_sale_buying_power.return_value = 100_000.0
    submitter = MagicMock()

    run_new_moon_cycle_live(
        new_moon_instant=_dt(2024, 9, 10),  # SELL season
        following_full_moon_instant=_dt(2024, 9, 25),
        astro=astro,
        qualifying_symbols=["AAA"],
        equity=100_000,
        prices={"AAA": 100.0},
        account=account,
        submitter=submitter,
    )

    account.fetch_short_sale_buying_power.assert_called_once()


def test_run_new_moon_cycle_live_sizes_down_when_fresh_buying_power_is_lower(
    stub_astro_source: type[StubAstroSource],
) -> None:
    """Proves the value genuinely flows through end-to-end (not a stale/ignored
    fetch): a low freshly-fetched buying-power reading visibly shrinks the order.
    quantity is shares, not dollars: $20,000 target capped to $5,000 by buying power,
    at a $100/share price -> 50 whole shares (IBKR rejects fractional-share orders)."""
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    account = MagicMock()
    account.fetch_buying_power.return_value = 5_000.0  # far below the 20,000 target
    account.fetch_short_sale_buying_power.return_value = 5_000.0
    submitter = MagicMock()

    result = run_new_moon_cycle_live(
        new_moon_instant=_dt(2024, 3, 10),
        following_full_moon_instant=_dt(2024, 3, 25),
        astro=astro,
        qualifying_symbols=["AAA"],
        equity=100_000,
        prices={"AAA": 100.0},
        account=account,
        submitter=submitter,
    )

    assert result.orders_submitted[0].quantity == 50.0  # sized down, not oversized


def test_run_new_moon_cycle_live_refetches_every_call_not_cached(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    account = MagicMock()
    account.fetch_buying_power.side_effect = [5_000.0, 20_000.0]
    account.fetch_short_sale_buying_power.side_effect = [5_000.0, 20_000.0]
    submitter = MagicMock()

    def _run() -> float:
        result = run_new_moon_cycle_live(
            new_moon_instant=_dt(2024, 3, 10),
            following_full_moon_instant=_dt(2024, 3, 25),
            astro=astro,
            qualifying_symbols=["AAA"],
            equity=100_000,
            prices={"AAA": 100.0},
            account=account,
            submitter=submitter,
        )
        return result.orders_submitted[0].quantity

    first = _run()
    second = _run()

    # quantity is shares at a fixed $100/share price: $5,000 -> 50 shares,
    # $20,000 (the uncapped 20% target itself) -> 200 shares
    assert first == 50.0
    assert second == 200.0
    assert account.fetch_buying_power.call_count == 2
