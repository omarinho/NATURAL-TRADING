"""Covers REQ-016's live-fetch requirement: the buying-power check must query a
freshly-fetched IBKR account value immediately before order submission, never a
stale/cached one. Mirrors tests/test_price_resolution.py's IBPriceClient coverage of
pricing/ibkr_prices.py — same "wrap a mocked ib_async IB connection" pattern."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from natural_trading.account.ibkr_account import IBAccountClient


def _account_value(tag: str, value: str) -> MagicMock:
    account_value = MagicMock()
    account_value.tag = tag
    account_value.value = value
    return account_value


def test_fetch_buying_power_uses_mocked_ib_account_summary() -> None:
    mock_ib = MagicMock()
    mock_ib.accountSummary.return_value = [
        _account_value("NetLiquidation", "150000"),
        _account_value("BuyingPower", "42000.50"),
    ]
    client = IBAccountClient(ib=mock_ib)

    result = client.fetch_buying_power()

    mock_ib.accountSummary.assert_called_once()
    assert result == 42000.50


def test_fetch_short_sale_buying_power_uses_mocked_ib_account_summary() -> None:
    mock_ib = MagicMock()
    mock_ib.accountSummary.return_value = [_account_value("BuyingPower", "10000")]
    client = IBAccountClient(ib=mock_ib)

    result = client.fetch_short_sale_buying_power()

    mock_ib.accountSummary.assert_called_once()
    assert result == 10000.0


def test_repeated_fetch_calls_reflect_fresh_ib_account_summary_not_cached() -> None:
    """REQ-016: 'immediately before submission' means each call must re-query IBKR —
    a client that reused a value from an earlier call would defeat the requirement."""
    mock_ib = MagicMock()
    mock_ib.accountSummary.side_effect = [
        [_account_value("BuyingPower", "10000")],
        [_account_value("BuyingPower", "25000")],
    ]
    client = IBAccountClient(ib=mock_ib)

    first = client.fetch_buying_power()
    second = client.fetch_buying_power()

    assert first == 10000.0
    assert second == 25000.0
    assert mock_ib.accountSummary.call_count == 2


def test_fetch_net_liquidation_uses_mocked_ib_account_summary() -> None:
    mock_ib = MagicMock()
    mock_ib.accountSummary.return_value = [
        _account_value("BuyingPower", "42000.50"),
        _account_value("NetLiquidation", "150000"),
    ]
    client = IBAccountClient(ib=mock_ib)

    result = client.fetch_net_liquidation()

    mock_ib.accountSummary.assert_called_once()
    assert result == 150000.0


def test_fetch_positions_returns_symbol_to_signed_size_map() -> None:
    mock_ib = MagicMock()
    long_position = MagicMock()
    long_position.contract.symbol = "AAPL"
    long_position.position = 10.0
    short_position = MagicMock()
    short_position.contract.symbol = "TSLA"
    short_position.position = -5.0
    mock_ib.positions.return_value = [long_position, short_position]
    client = IBAccountClient(ib=mock_ib)

    result = client.fetch_positions()

    assert result == {"AAPL": 10.0, "TSLA": -5.0}


def test_fetch_positions_returns_empty_dict_when_flat() -> None:
    mock_ib = MagicMock()
    mock_ib.positions.return_value = []
    client = IBAccountClient(ib=mock_ib)

    assert client.fetch_positions() == {}


def test_missing_buying_power_tag_raises_clear_error() -> None:
    mock_ib = MagicMock()
    mock_ib.accountSummary.return_value = [_account_value("NetLiquidation", "1000")]
    client = IBAccountClient(ib=mock_ib)

    with pytest.raises(ValueError, match="BuyingPower"):
        client.fetch_buying_power()


def test_no_third_party_account_data_import_in_account_module() -> None:
    import inspect

    from natural_trading.account import ibkr_account

    source = inspect.getsource(ibkr_account)
    forbidden = ("import requests", "import httpx", "yfinance", "alpha_vantage")
    for token in forbidden:
        assert token not in source, f"ibkr_account.py references forbidden source {token!r}"
