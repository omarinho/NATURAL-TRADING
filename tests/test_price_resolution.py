"""Covers REQ-004 (weekend/holiday fallback for lunar phase day prices X/Y/Z/W),
REQ-005 (V's close/live/fallback resolution depending on session state), REQ-006
(all phase prices sourced from IBKR historical/live data only), and REQ-018's local
"day of" boundary wiring (INSTRUCTIONS.md's Additional Notes: 'day of' checks must be
evaluated in the local time implied by the configured coordinates, not UTC)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from natural_trading.config import Coordinates
from natural_trading.pricing.ibkr_prices import IBPriceClient
from natural_trading.pricing.resolver import (
    DailyBar,
    local_date_of,
    resolve_phase_price,
    resolve_phase_price_for_instant,
    resolve_v_price,
    resolve_v_price_for_instant,
)
from natural_trading.pricing.session import SessionState, determine_session_state

BARS = [
    DailyBar(trading_date=date(2024, 6, 3), close=100.0),  # Monday
    DailyBar(trading_date=date(2024, 6, 4), close=101.0),
    DailyBar(trading_date=date(2024, 6, 5), close=102.0),
    DailyBar(trading_date=date(2024, 6, 6), close=103.0),
    DailyBar(trading_date=date(2024, 6, 7), close=104.0),  # Friday
]


# ─── REQ-004 ────────────────────────────────────────────────────────────────────────


def test_phase_day_on_saturday_resolves_to_prior_friday_close() -> None:
    saturday = date(2024, 6, 8)
    assert resolve_phase_price(BARS, saturday) == 104.0


def test_phase_day_on_market_holiday_resolves_to_most_recent_prior_close() -> None:
    holiday = date(2024, 6, 6)
    bars_without_holiday = [b for b in BARS if b.trading_date != holiday]
    assert resolve_phase_price(bars_without_holiday, holiday) == 102.0  # Jun 5 close


def test_phase_day_on_normal_trading_day_resolves_to_its_own_close() -> None:
    assert resolve_phase_price(BARS, date(2024, 6, 5)) == 102.0


# ─── REQ-005 ────────────────────────────────────────────────────────────────────────


def test_v_resolves_to_close_when_session_already_finished() -> None:
    result = resolve_v_price(
        bars=BARS,
        today=date(2024, 6, 7),
        session_state=SessionState.CLOSED_AFTER_SESSION,
        fetch_live_price=lambda: pytest.fail("should not fetch a live price"),
    )
    assert result == 104.0


def test_v_resolves_to_live_price_during_active_market_hours() -> None:
    result = resolve_v_price(
        bars=BARS[:-1],  # today's close bar not available yet
        today=date(2024, 6, 7),
        session_state=SessionState.OPEN,
        fetch_live_price=lambda: 105.5,
    )
    assert result == 105.5


def test_v_resolves_to_last_close_on_weekend_or_holiday_not_a_live_quote() -> None:
    result = resolve_v_price(
        bars=BARS,
        today=date(2024, 6, 8),  # Saturday, no session
        session_state=SessionState.NO_SESSION,
        fetch_live_price=lambda: pytest.fail("must not fetch a live price on a no-session day"),
    )
    assert result == 104.0


# ─── REQ-006 ────────────────────────────────────────────────────────────────────────


def test_historical_close_fetch_uses_mocked_ib_reqhistoricaldata_only() -> None:
    mock_ib = MagicMock()
    mock_bar = MagicMock()
    mock_bar.date = date(2024, 6, 5)
    mock_bar.close = 102.0
    mock_ib.reqHistoricalData.return_value = [mock_bar]

    client = IBPriceClient(ib=mock_ib)
    bars = client.fetch_daily_bars("AAPL")

    mock_ib.reqHistoricalData.assert_called_once()
    assert bars == [DailyBar(trading_date=date(2024, 6, 5), close=102.0)]


def test_live_price_fetch_uses_mocked_ib_live_quote_method() -> None:
    mock_ib = MagicMock()
    mock_ticker = MagicMock()
    mock_ticker.last = 210.25
    mock_ib.reqMktData.return_value = mock_ticker

    client = IBPriceClient(ib=mock_ib)
    price = client.fetch_live_price("AAPL")

    mock_ib.qualifyContracts.assert_called_once()  # populates conId before reqMktData
    mock_ib.reqMktData.assert_called_once()
    assert price == 210.25


def test_live_price_fetch_uses_mocked_ib_live_quote_method_session_reference() -> None:
    mock_ib = MagicMock()
    mock_details = MagicMock()
    mock_details.liquidHours = "20240605:0930-20240605:1600"
    mock_details.timeZoneId = "America/New_York"
    mock_ib.reqContractDetails.return_value = [mock_details]

    client = IBPriceClient(ib=mock_ib)
    liquid_hours, timezone_id = client.fetch_session_reference("SPY")

    mock_ib.reqContractDetails.assert_called_once()
    assert liquid_hours == "20240605:0930-20240605:1600"
    assert timezone_id == "America/New_York"


def test_fetch_session_reference_raises_clear_error_when_unresolvable() -> None:
    mock_ib = MagicMock()
    mock_ib.reqContractDetails.return_value = []
    client = IBPriceClient(ib=mock_ib)

    with pytest.raises(ValueError, match="SPY"):
        client.fetch_session_reference("SPY")


# ─── determine_session_state ────────────────────────────────────────────────────────

_TZ = "America/New_York"


def test_session_open_when_now_falls_inside_todays_liquid_hours() -> None:
    liquid_hours = "20240605:0930-20240605:1600"
    now_utc = datetime(2024, 6, 5, 15, 0, tzinfo=UTC)  # 11:00 ET
    assert determine_session_state(liquid_hours, _TZ, now_utc) is SessionState.OPEN


def test_session_closed_after_session_when_now_is_past_close() -> None:
    liquid_hours = "20240605:0930-20240605:1600"
    now_utc = datetime(2024, 6, 5, 22, 0, tzinfo=UTC)  # 18:00 ET
    assert determine_session_state(liquid_hours, _TZ, now_utc) is SessionState.CLOSED_AFTER_SESSION


def test_session_closed_after_session_when_now_is_before_open() -> None:
    """Before today's open there is no close bar yet either — treated the same as
    CLOSED_AFTER_SESSION since resolve_v_price falls back identically either way."""
    liquid_hours = "20240605:0930-20240605:1600"
    now_utc = datetime(2024, 6, 5, 9, 0, tzinfo=UTC)  # 05:00 ET
    assert determine_session_state(liquid_hours, _TZ, now_utc) is SessionState.CLOSED_AFTER_SESSION


def test_session_no_session_on_a_day_marked_closed() -> None:
    liquid_hours = "20240608:CLOSED"
    now_utc = datetime(2024, 6, 8, 15, 0, tzinfo=UTC)
    assert determine_session_state(liquid_hours, _TZ, now_utc) is SessionState.NO_SESSION


def test_session_no_session_when_todays_date_absent_from_string() -> None:
    liquid_hours = "20240603:0930-20240603:1600"  # only a different date present
    now_utc = datetime(2024, 6, 5, 15, 0, tzinfo=UTC)
    assert determine_session_state(liquid_hours, _TZ, now_utc) is SessionState.NO_SESSION


def test_no_third_party_market_data_import_in_pricing_module() -> None:
    pricing_dir = Path(__file__).resolve().parents[1] / "src" / "natural_trading" / "pricing"
    forbidden = ("import requests", "import httpx", "yfinance", "alpha_vantage")
    for py_file in pricing_dir.glob("*.py"):
        text = py_file.read_text()
        for token in forbidden:
            assert (
                token not in text
            ), f"{py_file.name} references forbidden third-party source {token!r}"


# ─── REQ-018 (local "day of" boundary uses configured coordinates, not raw UTC) ────

_GREENWICH = Coordinates(latitude=0.0, longitude=0.0)
_BOGOTA = Coordinates(latitude=4.73104, longitude=-74.0417)
# 03:00 UTC on a Thursday: at longitude 0 this is still June 6 local; Bogota's
# longitude (-74.0417) shifts local time back by ~4h56m, landing on June 5.
_NEAR_MIDNIGHT_INSTANT = datetime(2024, 6, 6, 3, 0, tzinfo=UTC)


def test_local_date_of_shifts_across_a_utc_day_boundary_with_longitude() -> None:
    assert local_date_of(_NEAR_MIDNIGHT_INSTANT, _GREENWICH) == date(2024, 6, 6)
    assert local_date_of(_NEAR_MIDNIGHT_INSTANT, _BOGOTA) == date(2024, 6, 5)


def test_resolve_phase_price_for_instant_changes_with_coordinates_no_code_change() -> None:
    """Same instant, same bars — only `coordinates` differs — and the resolved phase
    price differs, proving coordinates.input genuinely affects computed output."""
    price_at_greenwich = resolve_phase_price_for_instant(BARS, _NEAR_MIDNIGHT_INSTANT, _GREENWICH)
    price_at_bogota = resolve_phase_price_for_instant(BARS, _NEAR_MIDNIGHT_INSTANT, _BOGOTA)

    assert price_at_greenwich == 103.0  # local date June 6 -> its own close
    assert price_at_bogota == 102.0  # local date June 5 -> its own close
    assert price_at_greenwich != price_at_bogota


def test_resolve_v_price_for_instant_uses_local_date_for_session_boundary() -> None:
    def _no_live_fetch() -> float:
        raise AssertionError("no live fetch expected — both dates have a close bar")

    result_greenwich = resolve_v_price_for_instant(
        BARS,
        _NEAR_MIDNIGHT_INSTANT,
        _GREENWICH,
        SessionState.CLOSED_AFTER_SESSION,
        _no_live_fetch,
    )
    result_bogota = resolve_v_price_for_instant(
        BARS,
        _NEAR_MIDNIGHT_INSTANT,
        _BOGOTA,
        SessionState.CLOSED_AFTER_SESSION,
        _no_live_fetch,
    )

    assert result_greenwich == 103.0
    assert result_bogota == 102.0
