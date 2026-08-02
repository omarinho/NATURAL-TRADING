"""REQ-011: only MARKET orders are ever produced — this module has no branch that
builds a limit-price order. REQ-013: no protective exit orders of any kind — this
module exposes only opening/closing MARKET order builders, nothing that reacts to
price movement between New Moon and Full Moon."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from natural_trading.astro.season import Season

ORDER_TYPE_MARKET = "MKT"


class OrderAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class TradeOrder:
    symbol: str
    action: OrderAction
    quantity: float
    order_type: str = ORDER_TYPE_MARKET


def build_opening_order(symbol: str, quantity: float, season: Season) -> TradeOrder:
    """REQ-009: BUY-to-open during BUY season, SELL-to-open (short) during SELL season."""
    action = OrderAction.BUY if season is Season.BUY else OrderAction.SELL
    return TradeOrder(symbol=symbol, action=action, quantity=quantity)


def build_closing_order(symbol: str, held_quantity: float, was_long: bool) -> TradeOrder:
    """REQ-010: flatten the full held quantity. LONG -> SELL, SHORT -> BUY-to-cover."""
    action = OrderAction.SELL if was_long else OrderAction.BUY
    return TradeOrder(symbol=symbol, action=action, quantity=abs(held_quantity))


def build_opening_orders(
    symbols: list[str], quantities: dict[str, float], season: Season
) -> list[TradeOrder]:
    return [build_opening_order(symbol, quantities[symbol], season) for symbol in symbols]


def build_closing_orders(open_positions: dict[str, float]) -> list[TradeOrder]:
    """`open_positions`: symbol -> signed quantity (positive = long, negative = short)."""
    return [
        build_closing_order(symbol, qty, was_long=qty > 0) for symbol, qty in open_positions.items()
    ]
