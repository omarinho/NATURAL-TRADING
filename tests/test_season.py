"""Covers REQ-001 (season detection uses the exact solstice instant, never a calendar
date) and REQ-002 (solstice-straddling lunar cycles are skipped entirely)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from natural_trading.astro.base import SolsticeKind
from natural_trading.astro.season import Season, determine_season, is_solstice_straddling_cycle
from tests.conftest import StubAstroSource

UTC = UTC


def _dt(y: int, m: int, d: int, h: int = 0) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


# ─── REQ-001 ────────────────────────────────────────────────────────────────────────


def test_instant_strictly_between_winter_and_summer_solstice_is_buy(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    assert determine_season(_dt(2024, 3, 15), astro) is Season.BUY


def test_instant_strictly_between_summer_and_winter_solstice_is_sell(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22), _dt(2024, 12, 21)],
        summer_solstices=[_dt(2024, 6, 20)],
    )
    assert determine_season(_dt(2024, 9, 15), astro) is Season.SELL


def test_instant_exactly_at_winter_solstice_transitions_to_buy(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2024, 12, 21)],
        summer_solstices=[_dt(2024, 6, 20)],
    )
    assert determine_season(_dt(2024, 12, 21), astro) is Season.BUY


def test_instant_exactly_at_summer_solstice_transitions_to_sell(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2024, 6, 20)],
    )
    assert determine_season(_dt(2024, 6, 20), astro) is Season.SELL


def test_season_lookup_uses_astro_source_abstraction_not_hardcoded_date() -> None:
    mock_astro = MagicMock()
    mock_astro.solstice_at_or_before.side_effect = [_dt(2024, 12, 21), _dt(2024, 6, 20)]

    determine_season(_dt(2025, 1, 5), mock_astro)

    assert mock_astro.solstice_at_or_before.call_count == 2
    called_kinds = {call.args[1] for call in mock_astro.solstice_at_or_before.call_args_list}
    assert called_kinds == {SolsticeKind.WINTER, SolsticeKind.SUMMER}

    # Static check: season.py contains no datetime literal construction of its own —
    # it only ever asks the astro-source abstraction for instants.
    season_src = (
        Path(__file__).resolve().parents[1] / "src" / "natural_trading" / "astro" / "season.py"
    )
    source_text = season_src.read_text()
    assert "datetime(" not in source_text
    assert "12, 21" not in source_text
    assert "6, 20" not in source_text


# ─── REQ-002 ────────────────────────────────────────────────────────────────────────


def test_new_moon_in_season_a_full_moon_in_season_b_is_straddling(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    new_moon = _dt(2024, 6, 1)  # BUY season (after winter, before summer)
    full_moon = _dt(2024, 6, 30)  # SELL season (after summer)
    assert is_solstice_straddling_cycle(new_moon, full_moon, astro) is True


def test_new_moon_in_season_b_full_moon_in_season_a_mirror_is_straddling(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22), _dt(2024, 12, 21)],
        summer_solstices=[_dt(2024, 6, 20)],
    )
    new_moon = _dt(2024, 12, 10)  # SELL season (after summer, before winter)
    full_moon = _dt(2025, 1, 5)  # BUY season (after winter)
    assert is_solstice_straddling_cycle(new_moon, full_moon, astro) is True


def test_new_moon_and_full_moon_same_season_is_not_straddling(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        winter_solstices=[_dt(2023, 12, 22)],
        summer_solstices=[_dt(2023, 6, 21), _dt(2024, 6, 20)],
    )
    new_moon = _dt(2024, 2, 1)
    full_moon = _dt(2024, 3, 1)
    assert is_solstice_straddling_cycle(new_moon, full_moon, astro) is False
