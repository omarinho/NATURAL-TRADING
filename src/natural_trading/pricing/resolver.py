"""REQ-004: weekend/holiday fallback for lunar phase day prices (X, Y, Z, W) — use the
most recent prior session's close. REQ-005: V (today's New Moon price) uses close,
live, or fallback price depending on session state. REQ-018 / INSTRUCTIONS.md's
Additional Notes: solstice and lunar-phase instants are single global UTC instants, but
"day of" checks (e.g. "the day of New Moon") must be evaluated in the local time
implied by the configured coordinates, not in UTC — `local_date_of` and the
`_for_instant` wrappers below are that wiring point."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from natural_trading.config import Coordinates
from natural_trading.pricing.session import SessionState


@dataclass(frozen=True)
class DailyBar:
    trading_date: date
    close: float


def closest_close_on_or_before(bars: Sequence[DailyBar], target: date) -> float | None:
    candidates = [b for b in bars if b.trading_date <= target]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.trading_date).close


def resolve_phase_price(bars: Sequence[DailyBar], target: date) -> float | None:
    """REQ-004: a normal trading day resolves to its own close (already the max bar
    date <= target); a weekend/holiday falls back to the most recent prior close."""
    return closest_close_on_or_before(bars, target)


def resolve_v_price(
    bars: Sequence[DailyBar],
    today: date,
    session_state: SessionState,
    fetch_live_price: Callable[[], float],
) -> float:
    """REQ-005: close if today's session already finished, live price if the market is
    currently open, or the last available prior close if today has no session at all
    (weekend/holiday) — never a live quote on a no-session day."""
    if session_state is SessionState.CLOSED_AFTER_SESSION:
        close = closest_close_on_or_before(bars, today)
        if close is None:
            raise ValueError("Session reported CLOSED_AFTER_SESSION but no close bar is available")
        return close
    if session_state is SessionState.OPEN:
        return fetch_live_price()
    # NO_SESSION: weekend/holiday — fall back to the last available prior close.
    close = closest_close_on_or_before(bars, today)
    if close is None:
        raise ValueError("No prior close bar available to resolve V on a no-session day")
    return close


def local_date_of(instant: datetime, coordinates: Coordinates) -> date:
    """REQ-018: converts a global UTC astronomical instant to the local calendar date
    implied by `coordinates`, via a longitude-based mean-solar-time offset (no
    timezone database needed — the same approach validated in
    preliminary/find_lunar_stocks.py's `local_date_of`, reused here as ordinary
    date-arithmetic, not the LLM-restricted pattern-check step, so REQ-003's
    zero-scripts rule does not apply to it). This is what makes `coordinates.input`
    genuinely observable: an instant near a UTC day boundary can resolve to a
    different local calendar day — and therefore a different weekend/holiday
    fallback outcome — purely because the configured longitude changed."""
    offset = timedelta(hours=coordinates.longitude / 15.0)
    return (instant + offset).date()


def resolve_phase_price_for_instant(
    bars: Sequence[DailyBar], instant: datetime, coordinates: Coordinates
) -> float | None:
    """Composes `local_date_of` with `resolve_phase_price` so a lunar-phase instant's
    weekend/holiday fallback (REQ-004) is evaluated against the LOCAL calendar day
    implied by `coordinates`, not the UTC day the instant happens to fall on."""
    return resolve_phase_price(bars, local_date_of(instant, coordinates))


def resolve_v_price_for_instant(
    bars: Sequence[DailyBar],
    instant: datetime,
    coordinates: Coordinates,
    session_state: SessionState,
    fetch_live_price: Callable[[], float],
) -> float:
    """Same local-date composition as `resolve_phase_price_for_instant`, applied to
    V's close/live/fallback resolution (REQ-005) — "today" is the local calendar day
    implied by `coordinates.input`, not `instant`'s raw UTC date."""
    return resolve_v_price(
        bars, local_date_of(instant, coordinates), session_state, fetch_live_price
    )
