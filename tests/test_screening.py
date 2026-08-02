"""Covers the lunar-stock pattern check (REQ-003: a pure, deterministic comparison of
the five phase-day close prices — X<Y<Z/Z>W>V for BUY, X>Y>Z/Z<W<V for SELL) and
REQ-017 (zero qualifying stocks is a valid, non-error outcome)."""

from __future__ import annotations

from natural_trading.astro.season import Season
from natural_trading.screening.llm_screen import PhasePrices, screen_candidate, screen_candidates

# ─── REQ-003 ────────────────────────────────────────────────────────────────────────


def test_buy_pattern_candidate_qualifies() -> None:
    prices = PhasePrices(x=10, y=12, z=15, w=13, v=11)  # X<Y<Z, Z>W, W>V
    assert screen_candidate(prices, Season.BUY) is True


def test_buy_pattern_candidate_fails_on_final_condition() -> None:
    """X<Y<Z and Z>W both hold, but W>V fails — must not qualify."""
    prices = PhasePrices(x=10, y=12, z=15, w=11, v=13)
    assert screen_candidate(prices, Season.BUY) is False


def test_sell_pattern_candidate_qualifies() -> None:
    prices = PhasePrices(x=15, y=12, z=10, w=12, v=14)  # X>Y>Z, Z<W, W<V
    assert screen_candidate(prices, Season.SELL) is True


def test_sell_pattern_candidate_fails_on_final_condition() -> None:
    """Confirmed against a real MSFT candidate (2026-07-14 New Moon, SELL season):
    X>Y>Z and Z<W both hold, but W<V fails (W=388.84 is NOT less than V=384.93) — must
    not qualify. An earlier LLM-based screening call misjudged this exact case."""
    prices = PhasePrices(x=390.74, y=379.4, z=368.57, w=388.84, v=384.93)
    assert screen_candidate(prices, Season.SELL) is False


def test_equal_values_do_not_qualify_either_season() -> None:
    """Strict inequality only — a flat sequence satisfies neither pattern."""
    prices = PhasePrices(x=10, y=10, z=10, w=10, v=10)
    assert screen_candidate(prices, Season.BUY) is False
    assert screen_candidate(prices, Season.SELL) is False


def test_buy_season_candidate_never_qualifies_under_sell_pattern() -> None:
    buy_prices = PhasePrices(x=10, y=12, z=15, w=13, v=11)
    assert screen_candidate(buy_prices, Season.SELL) is False


# ─── REQ-017 ────────────────────────────────────────────────────────────────────────


def test_screen_candidates_returns_only_qualifying_symbols() -> None:
    candidates = {
        "AAA": PhasePrices(x=10, y=12, z=15, w=13, v=11),  # qualifies (BUY)
        "BBB": PhasePrices(x=10, y=10, z=10, w=10, v=10),  # does not qualify
    }
    assert screen_candidates(candidates, Season.BUY) == ["AAA"]


def test_zero_qualifying_candidates_returns_empty_list_no_exception() -> None:
    candidates = {
        "AAA": PhasePrices(x=10, y=10, z=10, w=10, v=10),
        "BBB": PhasePrices(x=20, y=20, z=20, w=20, v=20),
    }
    result = screen_candidates(candidates, Season.BUY)
    assert result == []


def test_zero_qualifying_stocks_is_not_treated_as_error_condition() -> None:
    result = screen_candidates({}, Season.SELL)  # no exception is itself the assertion
    assert result == []
