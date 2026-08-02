"""Covers REQ-014 (equal-weight 1/N position sizing), REQ-015 (20% single-position
cap, excess left unused not redistributed), and REQ-016 (buying-power / short-sale
availability check before order submission)."""

from __future__ import annotations

import pytest

from natural_trading.sizing import (
    apply_buying_power_check,
    compute_position_sizes,
    equal_weight_fractions,
    shares_from_dollar_amount,
)

# ─── REQ-014 ────────────────────────────────────────────────────────────────────────


def test_three_qualifying_stocks_each_sized_at_one_third_pre_cap() -> None:
    fractions = equal_weight_fractions(["AAA", "BBB", "CCC"])
    assert fractions["AAA"] == pytest.approx(1 / 3)
    assert fractions["BBB"] == pytest.approx(1 / 3)
    assert fractions["CCC"] == pytest.approx(1 / 3)


def test_nine_qualifying_stocks_each_sized_at_one_ninth_pre_cap() -> None:
    symbols = [f"S{i}" for i in range(9)]
    fractions = equal_weight_fractions(symbols)
    assert all(f == pytest.approx(1 / 9) for f in fractions.values())


def test_position_size_not_increased_before_following_full_moon_no_pyramiding() -> None:
    sizes_at_new_moon = compute_position_sizes(["AAA"], equity=100_000)
    sizes_again = compute_position_sizes(["AAA"], equity=100_000)
    assert sizes_at_new_moon["AAA"].dollar_amount == sizes_again["AAA"].dollar_amount


# ─── REQ-015 ────────────────────────────────────────────────────────────────────────


def test_single_qualifying_stock_capped_at_20_percent_80_percent_cash() -> None:
    sizes = compute_position_sizes(["AAA"], equity=100_000)
    assert sizes["AAA"].capped_fraction == pytest.approx(0.20)
    assert sizes["AAA"].dollar_amount == pytest.approx(20_000)


def test_four_qualifying_stocks_each_capped_at_20_percent_remainder_not_redistributed() -> None:
    sizes = compute_position_sizes(["A", "B", "C", "D"], equity=100_000)
    for result in sizes.values():
        assert result.target_fraction == pytest.approx(0.25)
        assert result.capped_fraction == pytest.approx(0.20)
        assert result.dollar_amount == pytest.approx(20_000)
    total_deployed = sum(r.dollar_amount for r in sizes.values())
    assert total_deployed == pytest.approx(80_000)  # remaining 20% left unused


def test_six_qualifying_stocks_under_cap_sizing_unchanged() -> None:
    symbols = [f"S{i}" for i in range(6)]
    sizes = compute_position_sizes(symbols, equity=100_000)
    expected = pytest.approx(1 / 6)
    for result in sizes.values():
        assert result.target_fraction == expected
        assert result.capped_fraction == expected  # cap (0.20) > 1/6, no change


# ─── REQ-016 ────────────────────────────────────────────────────────────────────────


def test_long_size_exceeding_buying_power_is_sized_down() -> None:
    assert (
        apply_buying_power_check(desired_dollar_amount=50_000, available_buying_power=30_000)
        == 30_000
    )


def test_short_size_exceeding_short_sale_buying_power_is_sized_down() -> None:
    assert (
        apply_buying_power_check(desired_dollar_amount=50_000, available_buying_power=10_000)
        == 10_000
    )


def test_shares_from_dollar_amount_floors_to_whole_shares() -> None:
    """IBKR rejects fractional-share MARKET orders (confirmed empirically: Error
    10243) — a $1,025.47 sized amount at $9.00/share must floor to 113 shares, not
    113.941... shares."""
    assert shares_from_dollar_amount(1_025.47, 9.00) == 113.0


def test_shares_from_dollar_amount_exact_division_no_fraction_introduced() -> None:
    assert shares_from_dollar_amount(20_000.0, 100.0) == 200.0


def test_shares_from_dollar_amount_below_one_share_price_returns_zero_shares() -> None:
    assert shares_from_dollar_amount(50.0, 100.0) == 0.0


def test_shares_from_dollar_amount_non_positive_price_returns_zero_not_a_crash() -> None:
    assert shares_from_dollar_amount(1_000.0, 0.0) == 0.0


def test_buying_power_check_uses_freshly_passed_account_value_not_stale() -> None:
    import natural_trading.sizing as sizing_module

    assert not hasattr(sizing_module, "_cached_buying_power")
    first = apply_buying_power_check(50_000, 40_000)
    second = apply_buying_power_check(50_000, 60_000)
    assert first == 40_000
    assert second == 50_000
