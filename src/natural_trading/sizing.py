"""REQ-014: equal-weight (1/N) position sizing across qualifying stocks. REQ-015:
20% single-position cap, excess left unused rather than redistributed. REQ-016:
buying-power / short-sale availability check before order submission."""

from __future__ import annotations

from dataclasses import dataclass

POSITION_CAP_FRACTION = 0.20


@dataclass(frozen=True)
class SizingResult:
    symbol: str
    target_fraction: float  # equal-weight fraction before the cap
    capped_fraction: float  # after the 20% cap
    dollar_amount: float  # capped_fraction * equity, before the buying-power check


def equal_weight_fractions(symbols: list[str]) -> dict[str, float]:
    """REQ-014: 1/N equal-weight split, N = number of qualifying symbols."""
    if not symbols:
        return {}
    weight = 1.0 / len(symbols)
    return {symbol: weight for symbol in symbols}


def apply_position_cap(fraction: float, cap: float = POSITION_CAP_FRACTION) -> float:
    """REQ-015: cap a single position's fraction; excess is NOT redistributed to the
    other positions — it is simply left unused (uncapped equal-weight amounts already
    at or below the cap pass through unchanged)."""
    return min(fraction, cap)


def compute_position_sizes(
    symbols: list[str], equity: float, cap: float = POSITION_CAP_FRACTION
) -> dict[str, SizingResult]:
    """Pure function of `symbols` and `equity` — sizing is set once at New Moon and
    recomputing with the same inputs is idempotent (REQ-014: no pyramiding)."""
    fractions = equal_weight_fractions(symbols)
    results: dict[str, SizingResult] = {}
    for symbol, fraction in fractions.items():
        capped = apply_position_cap(fraction, cap)
        results[symbol] = SizingResult(
            symbol=symbol,
            target_fraction=fraction,
            capped_fraction=capped,
            dollar_amount=capped * equity,
        )
    return results


def apply_buying_power_check(desired_dollar_amount: float, available_buying_power: float) -> float:
    """REQ-016: never submit an order sized beyond currently available buying power
    (longs) or short-sale buying power/borrow availability (shorts) — size down rather
    than submit oversized. `available_buying_power` must be a freshly-fetched value
    passed in by the caller immediately before submission; this function holds no
    cached/module-level state of its own."""
    if desired_dollar_amount <= available_buying_power:
        return desired_dollar_amount
    return max(available_buying_power, 0.0)


def shares_from_dollar_amount(dollar_amount: float, price_per_share: float) -> float:
    """Converts a sized dollar amount into a whole-share quantity for order
    submission — IBKR's API rejects fractional-share MARKET orders outright
    (confirmed empirically against the real paper Gateway: "Error 10243:
    Fractional-sized order cannot be placed via API"), so this always floors to the
    nearest whole share rather than passing a fractional dollar-per-share result
    straight through as a share count."""
    if price_per_share <= 0:
        return 0.0
    return float(int(dollar_amount // price_per_share))
