"""Covers REQ-018 (coordinates.input configurable, key=value, default Bogota),
REQ-020 (Anthropic API key from anthropic.input, never hardcoded, gitignored), and
REQ-022 (IBKR connection configurable; paper-to-live migration is a config change)."""

from __future__ import annotations

from pathlib import Path

import pytest

from natural_trading.config import (
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    load_anthropic_config,
    load_coordinates,
    load_ibkr_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "natural_trading"


# ─── REQ-018 ────────────────────────────────────────────────────────────────────────


def test_valid_lat_long_lines_parsed_into_expected_floats(tmp_path: Path) -> None:
    f = tmp_path / "coordinates.input"
    f.write_text("latitude=40.7128\nlongitude=-74.0060\n")
    coords = load_coordinates(f)
    assert coords.latitude == pytest.approx(40.7128)
    assert coords.longitude == pytest.approx(-74.0060)


def test_comment_lines_ignored_in_coordinates_input(tmp_path: Path) -> None:
    f = tmp_path / "coordinates.input"
    f.write_text("# comment\nlatitude=1.0\n# another\nlongitude=2.0\n")
    coords = load_coordinates(f)
    assert coords.latitude == 1.0
    assert coords.longitude == 2.0


@pytest.mark.parametrize(
    "latitude,longitude",
    [(4.73104, -74.0417), (51.5074, -0.1278), (-33.8688, 151.2093)],
)
def test_changing_file_values_changes_loader_output_no_code_change(
    tmp_path: Path, latitude: float, longitude: float
) -> None:
    f = tmp_path / "coordinates.input"
    f.write_text(f"latitude={latitude}\nlongitude={longitude}\n")
    coords = load_coordinates(f)
    assert coords.latitude == pytest.approx(latitude)
    assert coords.longitude == pytest.approx(longitude)


def test_default_coordinates_match_bogota_when_file_has_no_matching_keys(tmp_path: Path) -> None:
    f = tmp_path / "coordinates.input"
    f.write_text("# empty file, no keys\n")
    coords = load_coordinates(f)
    assert coords.latitude == pytest.approx(DEFAULT_LATITUDE) == pytest.approx(4.73104)
    assert coords.longitude == pytest.approx(DEFAULT_LONGITUDE) == pytest.approx(-74.0417)


def test_no_hardcoded_lat_long_literal_in_astro_calculation_modules() -> None:
    astro_dir = SRC_ROOT / "astro"
    for py_file in astro_dir.rglob("*.py"):
        text = py_file.read_text()
        assert "4.73104" not in text
        assert "74.0417" not in text


# ─── REQ-020 ────────────────────────────────────────────────────────────────────────


def test_anthropic_api_key_read_from_anthropic_input_at_runtime(tmp_path: Path) -> None:
    f = tmp_path / "anthropic.input"
    f.write_text("api_key=sk-ant-test-1234\n")
    cfg = load_anthropic_config(f)
    assert cfg.api_key == "sk-ant-test-1234"


def test_no_hardcoded_anthropic_api_key_literal_in_source() -> None:
    for py_file in SRC_ROOT.rglob("*.py"):
        assert "sk-ant-" not in py_file.read_text()


def test_gitignore_excludes_anthropic_input() -> None:
    gitignore_text = (REPO_ROOT / ".gitignore").read_text()
    assert "anthropic.input" in gitignore_text


def test_no_env_file_used_for_anthropic_api_key() -> None:
    assert not (REPO_ROOT / ".env").exists()
    for py_file in SRC_ROOT.rglob("*.py"):
        assert "dotenv" not in py_file.read_text().lower()


# ─── REQ-022 ────────────────────────────────────────────────────────────────────────


def test_ibkr_host_port_client_id_read_from_config_not_hardcoded(tmp_path: Path) -> None:
    f = tmp_path / "ibkr.input"
    f.write_text("host=127.0.0.1\nport=4002\nclient_id=7\n")
    cfg = load_ibkr_config(f)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 4002
    assert cfg.client_id == 7


def test_changing_configured_port_to_live_account_port_requires_no_source_change(
    tmp_path: Path,
) -> None:
    f = tmp_path / "ibkr.input"
    f.write_text("host=127.0.0.1\nport=7496\nclient_id=7\n")  # live-account port example
    cfg = load_ibkr_config(f)
    assert cfg.port == 7496


def test_no_hardcoded_ibkr_connection_literal_outside_config() -> None:
    for py_file in SRC_ROOT.rglob("*.py"):
        if py_file.name == "config.py":
            continue
        assert "127.0.0.1" not in py_file.read_text()
