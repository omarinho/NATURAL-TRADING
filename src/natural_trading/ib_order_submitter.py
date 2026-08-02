"""REQ-011/REQ-012: the live IBKR order-submission boundary — the only place a
TradeOrder actually reaches the market. Mirrors account/ibkr_account.py's pattern: a
thin dataclass wrapper over an ib_async `IB` connection, holding no state of its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from natural_trading.orders import TradeOrder

logger = logging.getLogger(__name__)

# Left unset, ib_async's Order.tif defaults to "" and IBKR fills it in server-side
# from this account's order preset — confirmed empirically to resolve to GTC, not
# DAY ("Error 10349: Order TIF was set to GTC based on order preset"). Explicit DAY
# removes that account-configuration dependency: a MARKET order not filled by end of
# session should expire, not sit live indefinitely.
TIME_IN_FORCE = "DAY"


@dataclass
class IBOrderSubmitter:
    """Submits a TradeOrder as a real IBKR MARKET order. No retry/queue/delay
    logic — REQ-012 requires immediate submission regardless of market hours; a
    MARKET order placed while the market is closed simply executes at the next
    session's open.

    Before submitting, checks the real margin impact via ib.whatIfOrder() — a
    generic account-level buying-power figure (accountSummary's BuyingPower tag,
    what account.ibkr_account.IBAccountClient.fetch_short_sale_buying_power still
    returns for the upfront sizing pass) does not accurately predict whether IBKR
    will actually accept a given SHORT order: margin requirements for shorting a
    specific security — especially a volatile/low-priced one, exactly the kind this
    system's momentum scanner tends to surface — can be far higher than the
    account's stated leverage suggests. Confirmed empirically against the real
    paper Gateway: a $10,000 BuyingPower figure (4x leverage) still had real short
    orders rejected needing $7,890 of initial margin against $2,500 of equity.
    whatIfOrder simulates the exact same margin engine IBKR's real
    order-acceptance check uses, so it predicts the real outcome per order instead
    of guessing from one general-purpose account-level number."""

    ib: Any

    def submit(self, order: TradeOrder) -> bool:
        """Returns True if the order was actually placed, False if it was skipped
        because the real (whatIfOrder-simulated) margin impact would be rejected."""
        from ib_async import MarketOrder, Stock

        contract = Stock(order.symbol, "SMART", "USD")
        ib_order = MarketOrder(order.action, order.quantity, tif=TIME_IN_FORCE)

        what_if = self.ib.whatIfOrder(contract, ib_order)
        if not hasattr(what_if, "equityWithLoanAfter"):
            # ib_async resolves whatIfOrder's future with an empty list, not an
            # OrderState, when IBKR rejects the underlying order outright (e.g. a
            # trading-permission/contract-status issue like error 201 "closing-only
            # status") rather than reporting a margin figure — confirmed empirically
            # against the real paper Gateway. No margin numbers exist to check in
            # that case, so treat it the same as a failed margin check: refuse to
            # place it. The IBKR client already logged the real error/reason.
            logger.warning(
                "Skipping %s %s %s — whatIfOrder was rejected by IBKR with no "
                "margin figures returned (see the preceding IBKR error log line).",
                order.action,
                order.quantity,
                order.symbol,
            )
            return False

        # ib_async's OrderState reports these as str fields, not floats (confirmed
        # empirically against the real paper Gateway) — comparing the raw strings
        # is a lexicographic trap ("100.00" < "99.00" is True by character order,
        # opposite of the numeric truth), so both must be cast before comparing.
        equity_with_loan_after = float(what_if.equityWithLoanAfter)
        init_margin_after = float(what_if.initMarginAfter)
        if equity_with_loan_after < init_margin_after:
            logger.warning(
                "Skipping %s %s %s — real margin check failed: equity with loan "
                "after ($%.2f) would be below the required initial margin ($%.2f).",
                order.action,
                order.quantity,
                order.symbol,
                equity_with_loan_after,
                init_margin_after,
            )
            return False

        self.ib.placeOrder(contract, ib_order)
        return True
