"""Covers REQ-007 (IBKR scanner candidate sourcing: batched, deduplicated, major US
exchanges, USD only, stop at 9 or exhausted) and REQ-008 (rights/warrants/ETFs
excluded from the candidate pool before pattern-matching)."""

from __future__ import annotations

from unittest.mock import MagicMock

from natural_trading.candidates.scanner import (
    filter_excluded,
    is_excluded_stock_type,
    pull_fresh_batch,
    run_candidate_search,
)


def _client_with_batches(batches: dict[str, list[str]]) -> MagicMock:
    client = MagicMock()
    client.scan.side_effect = lambda scan_code, location_code, currency: batches.get(scan_code, [])
    return client


# ─── REQ-007 ────────────────────────────────────────────────────────────────────────


def test_scanner_subscription_uses_major_us_exchanges_and_usd() -> None:
    client = _client_with_batches({"MOST_ACTIVE": ["AAA"]})
    pull_fresh_batch(client, seen=set(), scan_codes=iter(["MOST_ACTIVE"]), batch_size=1)
    client.scan.assert_called_once_with("MOST_ACTIVE", location_code="STK.US.MAJOR", currency="USD")


def test_symbol_seen_earlier_is_deduplicated_in_later_batch() -> None:
    client = _client_with_batches(
        {
            "MOST_ACTIVE": ["AAA", "BBB"],
            "HOT_BY_VOLUME": ["BBB", "CCC"],
        }
    )
    seen = {"BBB"}
    batch = pull_fresh_batch(client, seen, iter(["MOST_ACTIVE", "HOT_BY_VOLUME"]), batch_size=10)
    assert batch == ["AAA", "CCC"]


def test_search_stops_mid_batch_once_ninth_qualifier_found() -> None:
    client = _client_with_batches({"MOST_ACTIVE": [f"S{i}" for i in range(20)]})
    client.stock_type.return_value = "COMMON"
    qualifies = MagicMock(return_value=True)

    found = run_candidate_search(
        client, qualifies, scan_codes=["MOST_ACTIVE"], batch_size=20, target_count=9
    )

    assert len(found) == 9
    assert qualifies.call_count == 9


def test_search_stops_when_scan_codes_exhausted_with_fewer_than_target() -> None:
    client = _client_with_batches({"MOST_ACTIVE": ["S1", "S2"]})
    client.stock_type.return_value = "COMMON"
    qualifies = MagicMock(return_value=False)

    found = run_candidate_search(
        client, qualifies, scan_codes=["MOST_ACTIVE"], batch_size=20, target_count=9
    )

    assert found == []


def test_batches_combine_multiple_scan_codes_to_reach_batch_size() -> None:
    client = _client_with_batches(
        {
            "MOST_ACTIVE": ["A1", "A2"],
            "HOT_BY_VOLUME": ["B1", "B2", "B3"],
        }
    )
    batch = pull_fresh_batch(client, set(), iter(["MOST_ACTIVE", "HOT_BY_VOLUME"]), batch_size=5)
    assert batch == ["A1", "A2", "B1", "B2", "B3"]


# ─── REQ-008 ────────────────────────────────────────────────────────────────────────


def test_right_stock_type_excluded_before_pattern_matching() -> None:
    assert is_excluded_stock_type("RIGHT") is True


def test_warrant_stock_type_excluded_before_pattern_matching() -> None:
    assert is_excluded_stock_type("WARRANT") is True


def test_etf_stock_type_excluded_before_pattern_matching() -> None:
    assert is_excluded_stock_type("ETF") is True


def test_ordinary_common_stock_retained_for_pattern_matching() -> None:
    assert is_excluded_stock_type("COMMON") is False


def test_filter_excluded_removes_only_excluded_types() -> None:
    client = MagicMock()
    client.stock_type.side_effect = lambda s: {"AAA": "COMMON", "BBB": "ETF", "CCC": "RIGHT"}[s]
    result = filter_excluded(client, ["AAA", "BBB", "CCC"])
    assert result == ["AAA"]
