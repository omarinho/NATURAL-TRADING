"""Covers REQ-021 (zero lunar-stock positions and zero new orders between Full Moon
and the following New Moon)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from natural_trading.state import (
    is_between_full_moon_and_new_moon,
    load_last_processed_trigger,
    positions_for_state,
    save_last_processed_trigger,
    should_submit_new_order,
)
from tests.conftest import StubAstroSource

UTC = UTC


def _dt(y: int, m: int, d: int, h: int = 0) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


def test_instant_strictly_between_full_moon_and_next_new_moon_holds_zero_positions(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        new_moons=[_dt(2024, 3, 10), _dt(2024, 4, 8)], full_moons=[_dt(2024, 3, 25)]
    )
    instant = _dt(2024, 4, 1)  # after Full Moon (Mar 25), before next New Moon (Apr 8)
    assert is_between_full_moon_and_new_moon(instant, astro) is True
    assert positions_for_state(instant, astro, currently_open={"AAA": 100.0}) == {}


def test_instant_strictly_between_full_moon_and_next_new_moon_submits_no_new_order(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(
        new_moons=[_dt(2024, 3, 10), _dt(2024, 4, 8)], full_moons=[_dt(2024, 3, 25)]
    )
    instant = _dt(2024, 4, 1)
    assert should_submit_new_order(instant, astro) is False


def test_instant_during_active_cycle_is_not_between_full_moon_and_new_moon(
    stub_astro_source: type[StubAstroSource],
) -> None:
    astro = stub_astro_source(new_moons=[_dt(2024, 3, 10)], full_moons=[_dt(2024, 2, 20)])
    instant = _dt(2024, 3, 15)  # after New Moon, before Full Moon -> active cycle
    assert is_between_full_moon_and_new_moon(instant, astro) is False
    assert should_submit_new_order(instant, astro) is True


# ─── load/save_last_processed_trigger (cold-start catch-up persistence) ────────────


def test_load_returns_none_when_state_file_does_not_exist(tmp_path: Path) -> None:
    assert load_last_processed_trigger(tmp_path / "missing.state") is None


def test_load_returns_none_for_an_empty_state_file(tmp_path: Path) -> None:
    path = tmp_path / "last_trigger.state"
    path.write_text("")
    assert load_last_processed_trigger(path) is None


def test_save_then_load_round_trips_the_exact_instant(tmp_path: Path) -> None:
    path = tmp_path / "last_trigger.state"
    instant = _dt(2026, 8, 12, 17)

    save_last_processed_trigger(path, instant)
    result = load_last_processed_trigger(path)

    assert result == instant


def test_save_overwrites_the_previous_value_not_appends(tmp_path: Path) -> None:
    path = tmp_path / "last_trigger.state"
    save_last_processed_trigger(path, _dt(2026, 7, 14))
    save_last_processed_trigger(path, _dt(2026, 8, 12))

    assert load_last_processed_trigger(path) == _dt(2026, 8, 12)
