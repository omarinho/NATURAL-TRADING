"""REQ-009: scheduler fires at the exact New Moon instant and creates MARKET opening
orders. REQ-010: fires at the exact Full Moon instant and creates MARKET closing
orders. REQ-012: orders are submitted immediately at the exact instant regardless of
market hours — no wait/delay/queue step postpones submission to the next session.
REQ-016: `run_new_moon_cycle_live` is the caller that fetches a fresh buying-power
reading immediately before sizing/order submission — see account/ibkr_account.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from natural_trading.astro.base import AstroSource, MoonPhase
from natural_trading.astro.season import Season, determine_season, is_solstice_straddling_cycle
from natural_trading.orders import TradeOrder, build_closing_orders, build_opening_orders
from natural_trading.sizing import (
    apply_buying_power_check,
    compute_position_sizes,
    shares_from_dollar_amount,
)


class OrderSubmitter(Protocol):
    def submit(self, order: TradeOrder) -> bool: ...


class AccountClient(Protocol):
    """REQ-016: the live-fetch boundary `run_new_moon_cycle_live` queries immediately
    before sizing/order submission — see account.ibkr_account.IBAccountClient for the
    real ib_async-backed implementation."""

    def fetch_buying_power(self) -> float: ...
    def fetch_short_sale_buying_power(self) -> float: ...
    def fetch_positions(self) -> dict[str, float]: ...


@dataclass(frozen=True)
class NewMoonCycleResult:
    orders_submitted: list[TradeOrder]
    skipped_straddle: bool


def next_trigger_instant(now: datetime, astro: AstroSource) -> tuple[datetime, MoonPhase]:
    """REQ-009/010/012: the next trigger is whichever of the next New Moon or next Full
    Moon comes first, computed from the astro source — never a fixed cron/day offset."""
    next_new = astro.moon_phase_after(now, MoonPhase.NEW)
    next_full = astro.moon_phase_after(now, MoonPhase.FULL)
    if next_new <= next_full:
        return next_new, MoonPhase.NEW
    return next_full, MoonPhase.FULL


def most_recent_trigger_instant(now: datetime, astro: AstroSource) -> tuple[datetime, MoonPhase]:
    """The mirror of `next_trigger_instant`: the most recent New Moon or Full Moon at
    or before `now`. Used by `resolve_next_action` to detect a trigger that already
    happened but may not yet have been processed — e.g. a cold process start shortly
    after the real instant, rather than a continuously-running loop that was already
    asleep waiting for it."""
    last_new = astro.moon_phase_at_or_before(now, MoonPhase.NEW)
    last_full = astro.moon_phase_at_or_before(now, MoonPhase.FULL)
    if last_new >= last_full:
        return last_new, MoonPhase.NEW
    return last_full, MoonPhase.FULL


# How close a freshly-computed "most recent trigger" instant must be to
# `last_processed` to count as the same real event, not a new one. A restart may
# recompute the same event via a different astro backend (USNO vs ephem fallback),
# which can legitimately differ by seconds/minutes without being a different event —
# comparing for exact equality would risk treating an already-processed trigger as
# unprocessed and resubmitting it (REQ-014 forbids pyramiding). Far smaller than the
# ~14.75-day gap between adjacent triggers, so there's no risk of conflating two
# genuinely different ones.
ALREADY_PROCESSED_TOLERANCE = timedelta(hours=1)

# How long after a trigger's real instant a cold start will still catch up on it,
# rather than silently skipping to the next one ~14.75 days later. Generous enough to
# absorb a late start (overslept an alarm, a Gateway hiccup, a slow reconnect) while
# still being an intentional, bounded window rather than "process anything, whenever."
CATCH_UP_WINDOW = timedelta(hours=3)


def resolve_next_action(
    now: datetime, astro: AstroSource, last_processed: datetime | None
) -> tuple[datetime, MoonPhase]:
    """What a process should do right now: catch up on a recent trigger that already
    happened but hasn't been processed yet (within `CATCH_UP_WINDOW` of `now`), or
    fall through to `next_trigger_instant`'s normal wait-for-the-next-one behavior.

    This is what makes a cold start safe against being a little late — without it, a
    process that starts even one second after a trigger's exact instant would compute
    the *next* one (~14.75 days away) and silently skip the trigger that just
    happened, with no error and nothing to notice until far too late."""
    recent_instant, recent_phase = most_recent_trigger_instant(now, astro)
    already_processed = (
        last_processed is not None
        and abs(recent_instant - last_processed) < ALREADY_PROCESSED_TOLERANCE
    )
    if not already_processed and now - recent_instant <= CATCH_UP_WINDOW:
        return recent_instant, recent_phase
    return next_trigger_instant(now, astro)


def run_new_moon_cycle(
    new_moon_instant: datetime,
    following_full_moon_instant: datetime,
    astro: AstroSource,
    qualifying_symbols: list[str],
    equity: float,
    buying_power: float,
    short_sale_buying_power: float,
    prices: dict[str, float],
    submitter: OrderSubmitter,
    already_held_symbols: frozenset[str] = frozenset(),
) -> NewMoonCycleResult:
    """Runs synchronously to completion with no sleep/wait/queue step — REQ-012
    requires orders to be submitted immediately regardless of market hours.

    `prices` (symbol -> current price per share) converts each symbol's sized dollar
    amount into a whole-share order quantity via `shares_from_dollar_amount` — IBKR's
    API rejects fractional-share MARKET orders outright, and a dollar amount is not
    itself a share count.

    `already_held_symbols` (REQ-014 no-pyramiding + crash-recovery safety): a symbol
    with an existing non-zero position is never resubmitted, regardless of whether it
    still qualifies. This is what stops a crash-mid-cycle-then-restart from
    resubmitting an opening order for a symbol a partially-completed earlier attempt
    already filled — see state.py's save_last_processed_trigger docstring for why
    last_processed alone can't protect against that. Defaults to empty so direct
    callers that don't need this (e.g. most existing tests) are unaffected."""
    if is_solstice_straddling_cycle(new_moon_instant, following_full_moon_instant, astro):
        return NewMoonCycleResult(orders_submitted=[], skipped_straddle=True)

    season = determine_season(new_moon_instant, astro)
    sizes = compute_position_sizes(qualifying_symbols, equity)

    quantities: dict[str, float] = {}
    for symbol, result in sizes.items():
        bp = buying_power if season is Season.BUY else short_sale_buying_power
        dollar_amount = apply_buying_power_check(result.dollar_amount, bp)
        quantities[symbol] = shares_from_dollar_amount(dollar_amount, prices[symbol])

    # A sized dollar amount smaller than one share's price floors to 0 shares (e.g. a
    # thinly-capitalized account split across many candidates, some high-priced) —
    # IBKR rejects a 0-quantity order outright ("size value cannot be zero"), so skip
    # it here rather than submit an order guaranteed to fail. A symbol already held is
    # skipped for the same reason a zero-quantity one is: submitting would be wrong,
    # not just redundant.
    fundable_symbols = [
        s for s in qualifying_symbols if quantities[s] > 0 and s not in already_held_symbols
    ]
    orders = build_opening_orders(fundable_symbols, quantities, season)
    # submit() returns False (and does not place the order) when a real, per-order
    # whatIfOrder margin check would be rejected — orders_submitted reflects only
    # what was actually accepted, not everything attempted (see
    # ib_order_submitter.IBOrderSubmitter.submit's docstring for why a single
    # upfront buying-power figure can't predict this).
    actually_submitted = [order for order in orders if submitter.submit(order)]
    return NewMoonCycleResult(orders_submitted=actually_submitted, skipped_straddle=False)


def run_new_moon_cycle_live(
    new_moon_instant: datetime,
    following_full_moon_instant: datetime,
    astro: AstroSource,
    qualifying_symbols: list[str],
    equity: float,
    prices: dict[str, float],
    account: AccountClient,
    submitter: OrderSubmitter,
) -> NewMoonCycleResult:
    """REQ-016: the caller `run_new_moon_cycle` itself deliberately does not have —
    `run_new_moon_cycle` and `apply_buying_power_check` stay pure functions of whatever
    buying-power figures they are given. This function is the one IBKR-touching caller
    responsible for supplying a buying-power value that is never stale: it queries
    `account` for a fresh buying_power / short_sale_buying_power reading immediately
    before delegating to `run_new_moon_cycle`, so every New Moon cycle sizes against
    account state as of that instant, never a cached or reused figure from an earlier
    cycle.

    `prices` (symbol -> current price per share) is supplied by the caller rather than
    fetched fresh here on purpose: the caller already resolved each qualifying
    symbol's V (today's New Moon price) moments earlier while screening it — reusing
    that same value means sizing is computed against the exact price that made the
    candidate qualify, not a separately-fetched live quote that could differ (and
    would also mean 9 extra live-data requests for a price already known).

    Also queries `account.fetch_positions()` for the same reason: a symbol already
    held (non-zero position) is passed through as `already_held_symbols` so
    `run_new_moon_cycle` skips resubmitting an opening order for it — see that
    function's docstring for the crash-recovery scenario this guards against."""
    buying_power = account.fetch_buying_power()
    short_sale_buying_power = account.fetch_short_sale_buying_power()
    already_held_symbols = frozenset(
        symbol for symbol, quantity in account.fetch_positions().items() if quantity != 0
    )
    return run_new_moon_cycle(
        new_moon_instant=new_moon_instant,
        following_full_moon_instant=following_full_moon_instant,
        astro=astro,
        qualifying_symbols=qualifying_symbols,
        equity=equity,
        buying_power=buying_power,
        short_sale_buying_power=short_sale_buying_power,
        prices=prices,
        submitter=submitter,
        already_held_symbols=already_held_symbols,
    )


def run_full_moon_cycle(
    open_positions: dict[str, float], submitter: OrderSubmitter
) -> list[TradeOrder]:
    """REQ-010: flattens every open lunar-stock position with a MARKET order,
    submitted immediately with no wait step. Closing orders reduce margin usage, so
    the real whatIfOrder check inside submit() should always pass in practice — but
    the returned list still reflects only what actually got submitted, for the same
    reason run_new_moon_cycle's does."""
    orders = build_closing_orders(open_positions)
    return [order for order in orders if submitter.submit(order)]
