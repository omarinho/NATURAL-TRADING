"""Covers the live IBKR order-submission boundary: submit() must translate a
TradeOrder into a real ib_async placeOrder() call, always as a MARKET order, with no
retry/queue/delay step (REQ-012). Mirrors tests/test_ibkr_account.py's "wrap a mocked
ib_async IB connection" pattern.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from natural_trading.ib_order_submitter import IBOrderSubmitter
from natural_trading.orders import OrderAction, TradeOrder


def test_submit_calls_place_order_on_ib() -> None:
    mock_ib = MagicMock()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=5)

    submitter.submit(order)

    mock_ib.placeOrder.assert_called_once()


def test_submit_uses_smart_usd_stock_contract() -> None:
    mock_ib = MagicMock()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="TSLA", action=OrderAction.SELL, quantity=3)

    submitter.submit(order)

    contract, _ = mock_ib.placeOrder.call_args[0]
    assert contract.symbol == "TSLA"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"


def test_submit_builds_market_order_with_correct_action_and_quantity() -> None:
    mock_ib = MagicMock()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=5)

    submitter.submit(order)

    _, ib_order = mock_ib.placeOrder.call_args[0]
    assert ib_order.action == "BUY"
    assert ib_order.totalQuantity == 5
    assert ib_order.orderType == "MKT"


def test_submit_forces_day_time_in_force_not_account_preset() -> None:
    """Left unset, IBKR fills tif in server-side from this account's order preset,
    which resolves to GTC, not DAY (confirmed empirically: Error 10349). An
    unfilled MARKET order should expire at end of session, not sit live
    indefinitely."""
    mock_ib = MagicMock()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=5)

    submitter.submit(order)

    _, ib_order = mock_ib.placeOrder.call_args[0]
    assert ib_order.tif == "DAY"


def test_submit_sell_action_builds_sell_market_order() -> None:
    mock_ib = MagicMock()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="TSLA", action=OrderAction.SELL, quantity=3)

    submitter.submit(order)

    _, ib_order = mock_ib.placeOrder.call_args[0]
    assert ib_order.action == "SELL"


@patch("ib_async.Stock")
def test_submit_does_not_retry_or_queue(mock_stock: MagicMock) -> None:
    """REQ-012: submission is a single direct call, no wait/queue step."""
    mock_ib = MagicMock()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=1)

    submitter.submit(order)

    assert mock_ib.placeOrder.call_count == 1
