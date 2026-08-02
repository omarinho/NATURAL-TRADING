"""Session-state classification used to resolve V (today's New Moon price) per
REQ-005: whether today's trading session has already closed, is currently open, or
does not exist at all (weekend/holiday)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class SessionState(StrEnum):
    OPEN = "open"
    CLOSED_AFTER_SESSION = "closed_after_session"
    NO_SESSION = "no_session"


def determine_session_state(liquid_hours: str, timezone_id: str, now_utc: datetime) -> SessionState:
    """Parses IBKR ContractDetails.liquidHours (e.g.
    "20260802:CLOSED;20260803:0930-20260803:1600;...", one semicolon-separated segment
    per date in the contract's own exchange timezone) and classifies today's segment.

    A today-segment found but not yet started (`now_local < start`) has no close bar
    yet either, so it is classified CLOSED_AFTER_SESSION rather than a fourth state —
    resolver.py's resolve_v_price treats CLOSED_AFTER_SESSION and NO_SESSION
    identically (fall back to the most recent prior close), so this only matters for
    picking an accurate label, not for the resolved price.
    """
    tz = ZoneInfo(timezone_id)
    now_local = now_utc.astimezone(tz)
    today_str = now_local.strftime("%Y%m%d")

    for segment in liquid_hours.split(";"):
        date_part = segment.split(":", 1)[0]
        if date_part != today_str:
            continue
        if segment.endswith(":CLOSED"):
            return SessionState.NO_SESSION
        # Each side of the dash is its own full "YYYYMMDD:HHMM" token.
        start_str, end_str = segment.split("-")
        start = datetime.strptime(start_str, "%Y%m%d:%H%M").replace(tzinfo=tz)
        end = datetime.strptime(end_str, "%Y%m%d:%H%M").replace(tzinfo=tz)
        if now_local < start:
            return SessionState.CLOSED_AFTER_SESSION
        if now_local <= end:
            return SessionState.OPEN
        return SessionState.CLOSED_AFTER_SESSION

    return SessionState.NO_SESSION
