"""Primary astro source — the USNO (US Naval Observatory) Astronomical Applications
API. Free, no API key, official U.S. government data service; used for both moon-phase
events (New/First Quarter/Full/Last Quarter) and Earth's Seasons (solstice/equinox)
events. See plan.json's astro_source_decision for the source-selection rationale.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any

import httpx

from natural_trading.astro.base import MoonPhase, SolsticeKind
from natural_trading.config import Coordinates

USNO_BASE_URL = "https://aa.usno.navy.mil/api"

# A given year's moon-phase/solstice data is astronomically fixed, so retrying and
# caching are both safe for the lifetime of one UsnoSource instance.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.5

_PHASE_NAME = {
    MoonPhase.NEW: "New Moon",
    MoonPhase.FIRST_QUARTER: "First Quarter",
    MoonPhase.FULL: "Full Moon",
    MoonPhase.LAST_QUARTER: "Last Quarter",
}


def _entry_to_datetime(entry: dict[str, Any]) -> datetime:
    """Both /moon/phases/year and /seasons entries carry a "time": "HH:MM" field
    (confirmed against the live API) giving the exact instant, not just the calendar
    date — dropping it and combining with midnight would silently understate REQ-009's
    "exact instant" by up to 24 hours."""
    event_date = date(entry["year"], entry["month"], entry["day"])
    hour_str, minute_str = entry["time"].split(":")
    return datetime.combine(event_date, datetime.min.time(), tzinfo=UTC).replace(
        hour=int(hour_str), minute=int(minute_str)
    )


class UsnoSource:
    def __init__(
        self,
        coordinates: Coordinates | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        # REQ-018: New Moon and solstice instants are geocentric — the USNO API's
        # /moon/phases/year and /seasons endpoints (see `_moon_phases_in_year` and
        # `_seasons_in_year` below) take a `year` only, no observer location, so
        # `coordinates` does not alter the instant computed here. It is still accepted
        # and stored so the configured location genuinely flows end-to-end from
        # main.py through to this backend, not just to a value that gets logged and
        # dropped. See natural_trading.pricing.resolver.local_date_of for the local
        # "day of" boundary calculation where coordinates DO change observable output.
        self.coordinates = coordinates
        self._client = client or httpx.Client(timeout=timeout)
        # A calendar year's moon-phase/solstice data never changes, but every
        # candidate screened during a New Moon cycle independently computes X/Y/Z/W
        # via compute_phase_instants — without this cache, a single run redundantly
        # re-fetches the same 2-3 years' data hundreds of times, multiplying exposure
        # to the transient network errors this class already has to tolerate.
        self._year_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        last_error: Exception = RuntimeError("unreachable")
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.get(f"{USNO_BASE_URL}{path}", params=params)
                response.raise_for_status()
                result: dict[str, Any] = response.json()
                return result
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise  # a 4xx is a real client error, not transient -- don't retry
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise last_error

    def _moon_phases_in_year(self, year: int) -> list[dict[str, Any]]:
        cache_key = ("moon", year)
        if cache_key not in self._year_cache:
            data = self._get("/moon/phases/year", year=year)
            self._year_cache[cache_key] = data.get("phasedata", [])
        return self._year_cache[cache_key]

    def _seasons_in_year(self, year: int) -> list[dict[str, Any]]:
        cache_key = ("seasons", year)
        if cache_key not in self._year_cache:
            data = self._get("/seasons", year=year)
            self._year_cache[cache_key] = data.get("data", [])
        return self._year_cache[cache_key]

    def moon_phase_at_or_before(self, instant: datetime, phase: MoonPhase) -> datetime:
        return self._nearest_moon_phase(instant, phase, before=True)

    def moon_phase_after(self, instant: datetime, phase: MoonPhase) -> datetime:
        return self._nearest_moon_phase(instant, phase, before=False)

    def _nearest_moon_phase(self, instant: datetime, phase: MoonPhase, before: bool) -> datetime:
        candidates: list[datetime] = []
        for year in (instant.year - 1, instant.year, instant.year + 1):
            for entry in self._moon_phases_in_year(year):
                if entry.get("phase") != _PHASE_NAME[phase]:
                    continue
                candidates.append(_entry_to_datetime(entry))
        return self._select(candidates, instant, before)

    def solstice_at_or_before(self, instant: datetime, kind: SolsticeKind) -> datetime:
        return self._nearest_solstice(instant, kind, before=True)

    def solstice_after(self, instant: datetime, kind: SolsticeKind) -> datetime:
        return self._nearest_solstice(instant, kind, before=False)

    def _nearest_solstice(self, instant: datetime, kind: SolsticeKind, before: bool) -> datetime:
        # The real API returns a generic phenom of "Solstice" for BOTH the June and
        # December events (confirmed against the live endpoint — there is no
        # "Winter Solstice"/"Summer Solstice" string), so Northern-Hemisphere month
        # disambiguates: June (6) is the summer solstice, December (12) is winter.
        want_month = 12 if kind is SolsticeKind.WINTER else 6
        candidates: list[datetime] = []
        for year in (instant.year - 1, instant.year, instant.year + 1):
            for entry in self._seasons_in_year(year):
                if entry.get("phenom") != "Solstice" or entry.get("month") != want_month:
                    continue
                candidates.append(_entry_to_datetime(entry))
        return self._select(candidates, instant, before)

    @staticmethod
    def _select(candidates: list[datetime], instant: datetime, before: bool) -> datetime:
        if before:
            eligible = [c for c in candidates if c <= instant]
            if not eligible:
                raise ValueError(
                    "No USNO event at or before the given instant in the fetched range"
                )
            return max(eligible)
        eligible = [c for c in candidates if c > instant]
        if not eligible:
            raise ValueError("No USNO event after the given instant in the fetched range")
        return min(eligible)
