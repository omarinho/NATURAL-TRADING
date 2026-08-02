"""Covers the live IBKR order-submission boundary: submit() must translate a
TradeOrder into a real ib_async placeOrder() call, always as a MARKET order, with no
retry/queue/delay step (REQ-012). Mirrors tests/test_ibkr_account.py's "wrap a mocked
ib_async IB connection" pattern.

Also covers the real-margin pre-check: a generic account-level buying-power figure
(accountSummary's BuyingPower tag) does not accurately predict whether IBKR will accept
a given SHORT order — confirmed empirically against the real paper Gateway, where a
$10,000 BuyingPower figure still had real short orders rejected needing far more
initial margin than the account's $2,500 equity covered. submit() now calls
ib.whatIfOrder() first (the same margin engine IBKR's real acceptance check uses) and
skips placeOrder() if the simulated result would be rejected.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from natural_trading.ib_order_submitter import IBOrderSubmitter
from natural_trading.orders import OrderAction, TradeOrder


def _passing_what_if() -> SimpleNamespace:
    """A whatIfOrder result comfortably within margin — equityWithLoanAfter far
    exceeds initMarginAfter, so submit() should proceed to placeOrder()."""
    return SimpleNamespace(equityWithLoanAfter=10_000.0, initMarginAfter=100.0)


def _failing_what_if() -> SimpleNamespace:
    """A whatIfOrder result IBKR would reject — mirrors the real rejection seen
    against the paper Gateway (equity $2,498.98 < required initial margin $7,890.81)."""
    return SimpleNamespace(equityWithLoanAfter=2_498.98, initMarginAfter=7_890.81)


def test_submit_calls_place_order_on_ib() -> None:
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = _passing_what_if()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=5)

    submitter.submit(order)

    mock_ib.placeOrder.assert_called_once()


def test_submit_uses_smart_usd_stock_contract() -> None:
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = _passing_what_if()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="TSLA", action=OrderAction.SELL, quantity=3)

    submitter.submit(order)

    contract, _ = mock_ib.placeOrder.call_args[0]
    assert contract.symbol == "TSLA"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"


def test_submit_builds_market_order_with_correct_action_and_quantity() -> None:
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = _passing_what_if()
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
    mock_ib.whatIfOrder.return_value = _passing_what_if()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=5)

    submitter.submit(order)

    _, ib_order = mock_ib.placeOrder.call_args[0]
    assert ib_order.tif == "DAY"


def test_submit_sell_action_builds_sell_market_order() -> None:
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = _passing_what_if()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="TSLA", action=OrderAction.SELL, quantity=3)

    submitter.submit(order)

    _, ib_order = mock_ib.placeOrder.call_args[0]
    assert ib_order.action == "SELL"


@patch("ib_async.Stock")
def test_submit_does_not_retry_or_queue(mock_stock: MagicMock) -> None:
    """REQ-012: submission is a single direct call, no wait/queue step."""
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = _passing_what_if()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=1)

    submitter.submit(order)

    assert mock_ib.placeOrder.call_count == 1


# ─── Real-margin pre-check via whatIfOrder ───────────────────────────────────────────


def test_submit_checks_margin_via_what_if_order_before_placing() -> None:
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = _passing_what_if()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=5)

    submitter.submit(order)

    mock_ib.whatIfOrder.assert_called_once()
    what_if_contract, what_if_order = mock_ib.whatIfOrder.call_args[0]
    assert what_if_contract.symbol == "AAPL"
    assert what_if_order.action == "BUY"


def test_submit_returns_true_when_order_placed() -> None:
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = _passing_what_if()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=5)

    assert submitter.submit(order) is True


def test_submit_skips_place_order_when_margin_check_fails() -> None:
    """Mirrors the real rejection observed against the paper Gateway: a SHORT order
    whose simulated initial margin exceeds equity-with-loan-value must never reach
    placeOrder() — submitting it anyway is exactly what got rejected for real."""
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = _failing_what_if()
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="KUST", action=OrderAction.SELL, quantity=278)

    result = submitter.submit(order)

    assert result is False
    mock_ib.placeOrder.assert_not_called()


def test_submit_compares_margin_fields_numerically_not_as_strings() -> None:
    """ib_async's real OrderState reports equityWithLoanAfter/initMarginAfter as
    str fields (confirmed empirically against the real paper Gateway — e.g.
    '2498.98', not 2498.98). A raw string comparison is a lexicographic trap: for
    this pair, "100.00" < "99.00" is True (since '1' < '9' as characters) even
    though 100.00 > 99.00 numerically — which would wrongly skip a perfectly
    fundable order. submit() must cast to float before comparing."""
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = SimpleNamespace(
        equityWithLoanAfter="100.00", initMarginAfter="99.00"
    )
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=1)

    assert submitter.submit(order) is True
    mock_ib.placeOrder.assert_called_once()


def test_submit_skips_when_ib_rejects_the_what_if_request_itself() -> None:
    """ib_async's whatIfOrder() does not always return an OrderState: when IBKR
    rejects the underlying order outright (e.g. error 201 "closing-only status" —
    a trading-permission issue, not a margin shortfall), the wrapper resolves the
    future with an empty list instead — confirmed empirically against the real
    paper Gateway (CIGL). submit() must treat that as "cannot safely place this
    order" rather than crash with AttributeError on the missing margin fields."""
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = []
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="CIGL", action=OrderAction.SELL, quantity=527)

    result = submitter.submit(order)

    assert result is False
    mock_ib.placeOrder.assert_not_called()


def test_submit_margin_check_boundary_is_inclusive() -> None:
    """Equity exactly equal to required margin should pass (IBKR's own rejection
    message says the loan value must "exceed" the margin, i.e. equal is fine)."""
    mock_ib = MagicMock()
    mock_ib.whatIfOrder.return_value = SimpleNamespace(
        equityWithLoanAfter=1_000.0, initMarginAfter=1_000.0
    )
    submitter = IBOrderSubmitter(ib=mock_ib)
    order = TradeOrder(symbol="AAPL", action=OrderAction.BUY, quantity=1)

    assert submitter.submit(order) is True
    mock_ib.placeOrder.assert_called_once()
