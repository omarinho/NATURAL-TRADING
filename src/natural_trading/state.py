"""REQ-021: zero lunar-stock positions and zero new orders strictly between a Full
Moon and the following New Moon."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from natural_trading.astro.base import AstroSource, MoonPhase


def is_between_full_moon_and_new_moon(instant: datetime, astro: AstroSource) -> bool:
    """True when the most recent Full Moon is more recent than the most recent New
    Moon — i.e. `instant` falls strictly inside the cash-holding window."""
    last_full = astro.moon_phase_at_or_before(instant, MoonPhase.FULL)
    last_new = astro.moon_phase_at_or_before(instant, MoonPhase.NEW)
    return last_full > last_new


def positions_for_state(
    instant: datetime, astro: AstroSource, currently_open: dict[str, float]
) -> dict[str, float]:
    """Enforces REQ-021 as a read-time invariant: between Full Moon and the next New
    Moon the strategy holds zero lunar-stock exposure (closing already happened at the
    Full Moon trigger in scheduler.py; this is a state-assertion/logging helper)."""
    if is_between_full_moon_and_new_moon(instant, astro):
        return {}
    return dict(currently_open)


def should_submit_new_order(instant: datetime, astro: AstroSource) -> bool:
    """REQ-021: no new lunar-stock order may be submitted strictly between Full Moon
    and the following New Moon."""
    return not is_between_full_moon_and_new_moon(instant, astro)


def load_last_processed_trigger(path: Path) -> datetime | None:
    """The instant of the last trigger this process successfully completed, or None
    if the file doesn't exist / is empty (first-ever run — nothing to catch up on).
    Used by scheduler.resolve_next_action to make a cold start safe against being a
    little late without risking a double-processed trigger."""
    if not path.exists():
        return None
    text = path.read_text().strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def save_last_processed_trigger(path: Path, instant: datetime) -> None:
    """Written only after a trigger is fully processed (see main.py's loop) — a crash
    mid-processing leaves the file at its previous value, so a restart will still see
    that trigger as unprocessed. This protects against a late cold start, not against
    a crash partway through submitting orders; see resolve_next_action's docstring."""
    path.write_text(instant.astimezone(UTC).isoformat())
