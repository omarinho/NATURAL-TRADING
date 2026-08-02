"""Supplementary coverage for the astro-source primary/fallback wiring (USNO primary,
ephem offline fallback) referenced by REQ-001's acceptance criteria and plan.json's
astro_source_decision.builder_guidance: 'on network/timeout/non-2xx error, fall back
to EphemSource; log which source served each computed instant.'"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx

from natural_trading.astro.base import MoonPhase, SolsticeKind
from natural_trading.astro.combined import CombinedAstroSource
from natural_trading.astro.ephem_source import EphemSource
from natural_trading.astro.usno import UsnoSource
from natural_trading.config import Coordinates

UTC = UTC


def test_falls_back_to_ephem_when_primary_raises() -> None:
    primary = MagicMock()
    primary.solstice_at_or_before.side_effect = ConnectionError("USNO unreachable")
    fallback = MagicMock()
    fallback.solstice_at_or_before.return_value = datetime(2024, 12, 21, tzinfo=UTC)

    combined = CombinedAstroSource(primary=primary, fallback=fallback)
    result = combined.solstice_at_or_before(datetime(2025, 1, 1, tzinfo=UTC), SolsticeKind.WINTER)

    assert result == datetime(2024, 12, 21, tzinfo=UTC)
    fallback.solstice_at_or_before.assert_called_once()


def test_uses_primary_result_when_primary_succeeds() -> None:
    primary = MagicMock()
    primary.solstice_at_or_before.return_value = datetime(2024, 6, 20, tzinfo=UTC)
    fallback = MagicMock()

    combined = CombinedAstroSource(primary=primary, fallback=fallback)
    result = combined.solstice_at_or_before(datetime(2024, 7, 1, tzinfo=UTC), SolsticeKind.SUMMER)

    assert result == datetime(2024, 6, 20, tzinfo=UTC)
    fallback.solstice_at_or_before.assert_not_called()


# ─── REQ-018 (coordinates threaded through end-to-end to both backends) ────────────


def test_usno_source_accepts_and_stores_coordinates() -> None:
    coordinates = Coordinates(latitude=40.7128, longitude=-74.0060)
    source = UsnoSource(coordinates=coordinates)
    assert source.coordinates == coordinates


def test_usno_source_defaults_coordinates_to_none_when_not_given() -> None:
    source = UsnoSource()
    assert source.coordinates is None


def test_ephem_source_accepts_and_stores_coordinates() -> None:
    coordinates = Coordinates(latitude=51.5074, longitude=-0.1278)
    source = EphemSource(coordinates=coordinates)
    assert source.coordinates == coordinates


def test_ephem_source_defaults_coordinates_to_none_when_not_given() -> None:
    source = EphemSource()
    assert source.coordinates is None


# ─── UsnoSource real-API-shaped parsing (REQ-009: exact instant, not truncated) ────


def _mock_httpx_client(json_by_path: dict[str, dict]) -> MagicMock:
    """`json_by_path` maps a URL path substring (e.g. "/moon/phases/year") to the
    JSON body that endpoint should return, mirroring the real USNO API's shape."""
    client = MagicMock()

    def _get(url: str, params: dict) -> MagicMock:
        for path, body in json_by_path.items():
            if path in url:
                response = MagicMock()
                response.json.return_value = body
                response.raise_for_status.return_value = None
                return response
        raise AssertionError(f"unexpected URL in test: {url}")

    client.get.side_effect = _get
    return client


def test_usno_moon_phase_keeps_the_real_time_of_day_not_midnight() -> None:
    """The live USNO API returns a "time": "HH:MM" field alongside the date — this
    must feed the returned instant's hour/minute, not be silently dropped in favor of
    midnight (REQ-009 requires the exact instant, not just the correct day)."""
    client = _mock_httpx_client(
        {
            "/moon/phases/year": {
                "phasedata": [
                    {"year": 2026, "month": 8, "day": 12, "phase": "New Moon", "time": "17:37"},
                ]
            }
        }
    )
    source = UsnoSource(client=client)

    result = source.moon_phase_after(datetime(2026, 8, 1, tzinfo=UTC), MoonPhase.NEW)

    assert result == datetime(2026, 8, 12, 17, 37, tzinfo=UTC)


def test_usno_solstice_matches_generic_solstice_phenom_by_month() -> None:
    """The live USNO API returns phenom="Solstice" for BOTH June and December events
    — there is no "Winter Solstice"/"Summer Solstice" string — so matching must
    disambiguate by month, not by a phenom value the real API never actually sends."""
    client = _mock_httpx_client(
        {
            "/seasons": {
                "data": [
                    {"year": 2026, "month": 6, "day": 21, "phenom": "Solstice", "time": "08:24"},
                    {"year": 2026, "month": 12, "day": 21, "phenom": "Solstice", "time": "20:50"},
                    {"year": 2026, "month": 3, "day": 20, "phenom": "Equinox", "time": "14:46"},
                ]
            }
        }
    )
    source = UsnoSource(client=client)

    winter = source.solstice_at_or_before(datetime(2026, 12, 25, tzinfo=UTC), SolsticeKind.WINTER)
    summer = source.solstice_at_or_before(datetime(2026, 6, 25, tzinfo=UTC), SolsticeKind.SUMMER)

    assert winter == datetime(2026, 12, 21, 20, 50, tzinfo=UTC)
    assert summer == datetime(2026, 6, 21, 8, 24, tzinfo=UTC)


def _response(json_body: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = json_body
    return response


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    response = MagicMock()
    response.status_code = status_code
    return httpx.HTTPStatusError("error", request=MagicMock(), response=response)


def test_usno_retries_transient_5xx_and_succeeds_on_second_attempt() -> None:
    good = _response({"phasedata": []})
    bad = MagicMock()
    bad.raise_for_status.side_effect = _http_status_error(502)
    client = MagicMock()
    client.get.side_effect = [bad, good]
    source = UsnoSource(client=client)

    with patch("natural_trading.astro.usno.time.sleep"):
        result = source._moon_phases_in_year(2026)

    assert result == []
    assert client.get.call_count == 2


def test_usno_retries_transport_error_and_succeeds() -> None:
    client = MagicMock()
    client.get.side_effect = [httpx.ConnectError("reset"), _response({"phasedata": []})]
    source = UsnoSource(client=client)

    with patch("natural_trading.astro.usno.time.sleep"):
        result = source._moon_phases_in_year(2026)

    assert result == []
    assert client.get.call_count == 2


def test_usno_does_not_retry_a_4xx_client_error() -> None:
    bad = MagicMock()
    bad.raise_for_status.side_effect = _http_status_error(404)
    client = MagicMock()
    client.get.return_value = bad
    source = UsnoSource(client=client)

    try:
        source._moon_phases_in_year(2026)
        raise AssertionError("expected HTTPStatusError to propagate")
    except httpx.HTTPStatusError:
        pass

    assert client.get.call_count == 1  # no retry on a non-transient client error


def test_usno_gives_up_after_max_attempts_on_persistent_failure() -> None:
    client = MagicMock()
    client.get.side_effect = httpx.ConnectError("persistent")
    source = UsnoSource(client=client)

    with patch("natural_trading.astro.usno.time.sleep"):
        try:
            source._moon_phases_in_year(2026)
            raise AssertionError("expected ConnectError to propagate after retries")
        except httpx.ConnectError:
            pass

    assert client.get.call_count == 3  # MAX_ATTEMPTS, so CombinedAstroSource can still fall back


def test_usno_caches_year_data_never_refetches_same_year() -> None:
    client = MagicMock()
    client.get.return_value = _response({"phasedata": [], "data": []})
    source = UsnoSource(client=client)

    source._moon_phases_in_year(2026)
    source._moon_phases_in_year(2026)
    source._seasons_in_year(2026)
    source._seasons_in_year(2026)

    # one call for the moon-phases endpoint, one for the seasons endpoint -- the
    # second call to each is served from the in-process cache, not the network
    assert client.get.call_count == 2


def test_usno_solstice_ignores_equinox_and_other_phenom_entries() -> None:
    client = _mock_httpx_client(
        {
            "/seasons": {
                "data": [
                    {"year": 2026, "month": 3, "day": 20, "phenom": "Equinox", "time": "14:46"},
                    {"year": 2026, "month": 6, "day": 21, "phenom": "Solstice", "time": "08:24"},
                    {"year": 2026, "month": 7, "day": 6, "phenom": "Aphelion", "time": "17:30"},
                ]
            }
        }
    )
    source = UsnoSource(client=client)

    result = source.solstice_after(datetime(2026, 1, 1, tzinfo=UTC), SolsticeKind.SUMMER)

    assert result == datetime(2026, 6, 21, 8, 24, tzinfo=UTC)
