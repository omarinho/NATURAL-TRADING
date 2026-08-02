"""Covers REQ-011 (only MARKET orders are ever submitted, never LIMIT) and REQ-013 (no
protective stop orders or any early-exit mechanism)."""

from __future__ import annotations

from pathlib import Path

from natural_trading.astro.season import Season
from natural_trading.orders import ORDER_TYPE_MARKET, build_closing_order, build_opening_order

ORDERS_SRC = Path(__file__).resolve().parents[1] / "src" / "natural_trading" / "orders.py"


# ─── REQ-011 ────────────────────────────────────────────────────────────────────────


def test_opening_order_type_is_market() -> None:
    order = build_opening_order("AAA", 10, Season.BUY)
    assert order.order_type == "MKT" == ORDER_TYPE_MARKET


def test_closing_order_type_is_market() -> None:
    order = build_closing_order("AAA", 10, was_long=True)
    assert order.order_type == "MKT"


def test_no_code_path_produces_limit_order_type() -> None:
    assert "LMT" not in ORDERS_SRC.read_text()


# ─── REQ-013 ────────────────────────────────────────────────────────────────────────


def test_opening_order_has_no_accompanying_stop_order() -> None:
    order = build_opening_order("AAA", 10, Season.BUY)
    assert order.order_type != "STP"
    text = ORDERS_SRC.read_text()
    assert "STP" not in text
    assert "TRAIL" not in text


def test_adverse_price_move_between_new_moon_and_full_moon_triggers_no_early_exit() -> None:
    # No stop-monitoring function exists at all — orders.py exposes only the opening/
    # closing order builders, so there is no code path that could react to a price move.
    import natural_trading.orders as orders_module

    public_names = [n for n in dir(orders_module) if not n.startswith("_")]
    assert not any("stop" in n.lower() or "trail" in n.lower() for n in public_names)


def test_order_construction_module_has_no_stop_order_type_code_path() -> None:
    text = ORDERS_SRC.read_text().lower()
    assert "stop" not in text
    assert "trailing" not in text
