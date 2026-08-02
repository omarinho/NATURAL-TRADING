"""REQ-011/REQ-012: the live IBKR order-submission boundary — the only place a
TradeOrder actually reaches the market. Mirrors account/ibkr_account.py's pattern: a
thin dataclass wrapper over an ib_async `IB` connection, holding no state of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from natural_trading.orders import TradeOrder

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
    session's open."""

    ib: Any

    def submit(self, order: TradeOrder) -> None:
        from ib_async import MarketOrder, Stock

        contract = Stock(order.symbol, "SMART", "USD")
        ib_order = MarketOrder(order.action, order.quantity, tif=TIME_IN_FORCE)
        self.ib.placeOrder(contract, ib_order)
