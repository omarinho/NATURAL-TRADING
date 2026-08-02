"""Covers REQ-003 (lunar-stock screening is performed by an LLM, not a coded numeric
filter), REQ-017 (zero qualifying stocks is a valid outcome), and REQ-019 (screening is
invoked programmatically via the Anthropic Messages API for unattended runs)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock

from natural_trading.astro.season import Season
from natural_trading.screening.llm_screen import PhasePrices, screen_candidate, screen_candidates

SCREENING_SRC = (
    Path(__file__).resolve().parents[1] / "src" / "natural_trading" / "screening" / "llm_screen.py"
)


def _mock_client(qualifies: bool) -> MagicMock:
    client = MagicMock()
    client.create_message.return_value = json.dumps({"qualifies": qualifies})
    return client


# ─── REQ-003 ────────────────────────────────────────────────────────────────────────


def test_buy_pattern_candidate_classified_as_qualifying_by_mocked_llm() -> None:
    client = _mock_client(qualifies=True)
    prices = PhasePrices(x=10, y=12, z=15, w=13, v=11)  # X<Y<Z, Z>W, W>V
    assert screen_candidate(client, "AAA", prices, Season.BUY) is True


def test_sell_pattern_candidate_classified_as_qualifying_by_mocked_llm() -> None:
    client = _mock_client(qualifies=True)
    prices = PhasePrices(
        x=15, y=12, z=10, w=12, v=9
    )  # X>Y>Z, Z<W, W<V... V lower for SELL semantics
    assert screen_candidate(client, "BBB", prices, Season.SELL) is True


def test_non_matching_candidate_classified_as_not_qualifying() -> None:
    client = _mock_client(qualifies=False)
    prices = PhasePrices(x=10, y=10, z=10, w=10, v=10)
    assert screen_candidate(client, "CCC", prices, Season.BUY) is False


def test_screening_module_has_no_deterministic_xyzwv_comparison() -> None:
    tree = ast.parse(SCREENING_SRC.read_text())
    suspect_names = {"x", "y", "z", "w", "v"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            touched: set[str] = set()
            for operand in [node.left, *node.comparators]:
                if isinstance(operand, ast.Name):
                    touched.add(operand.id.lower())
                elif isinstance(operand, ast.Attribute):
                    touched.add(operand.attr.lower())
            assert not (
                touched & suspect_names
            ), f"Deterministic comparison found: {ast.dump(node)}"


def test_qualifies_true_parsed_from_markdown_fenced_response() -> None:
    """Real models sometimes wrap the answer in ```json fences despite being asked
    for a bare object — the parser must find the verdict regardless."""
    client = MagicMock()
    client.create_message.return_value = '```json\n{"qualifies": true}\n```'
    prices = PhasePrices(x=10, y=12, z=15, w=13, v=11)
    assert screen_candidate(client, "AAA", prices, Season.BUY) is True


def test_qualifies_parsed_from_response_with_reasoning_preamble() -> None:
    """The model is asked to reason step by step before its final JSON line — the
    parser must find the verdict at the end of a longer response, not require the
    entire response to be pure JSON."""
    client = MagicMock()
    client.create_message.return_value = (
        "Let's check each comparison.\n"
        "X > Y > Z: 15 > 12 > 10, true.\n"
        "Z < W: 10 < 12, true.\n"
        "W < V: 12 < 9, false.\n"
        "Not all conditions hold.\n"
        '{"qualifies": false}'
    )
    prices = PhasePrices(x=15, y=12, z=10, w=12, v=9)
    assert screen_candidate(client, "BBB", prices, Season.SELL) is False


def test_qualifies_defaults_to_false_when_no_json_object_found() -> None:
    client = MagicMock()
    client.create_message.return_value = "I'm not sure how to answer that."
    prices = PhasePrices(x=10, y=12, z=15, w=13, v=11)
    assert screen_candidate(client, "AAA", prices, Season.BUY) is False


def test_screening_call_made_via_anthropic_client_with_no_blocking_prompt() -> None:
    client = _mock_client(qualifies=True)
    prices = PhasePrices(x=10, y=12, z=15, w=13, v=11)
    screen_candidate(client, "AAA", prices, Season.BUY)
    client.create_message.assert_called_once()
    assert "input(" not in SCREENING_SRC.read_text()


# ─── REQ-017 ────────────────────────────────────────────────────────────────────────


def test_zero_qualifying_candidates_returns_empty_list_no_exception() -> None:
    client = _mock_client(qualifies=False)
    candidates = {
        "AAA": PhasePrices(x=10, y=10, z=10, w=10, v=10),
        "BBB": PhasePrices(x=20, y=20, z=20, w=20, v=20),
    }
    result = screen_candidates(client, candidates, Season.BUY)
    assert result == []


def test_zero_qualifying_stocks_is_not_treated_as_error_condition() -> None:
    client = _mock_client(qualifies=False)
    result = screen_candidates(client, {}, Season.SELL)  # no exception is itself the assertion
    assert result == []


# ─── REQ-019 ────────────────────────────────────────────────────────────────────────


def test_screening_executes_synchronously_without_interactive_input_in_unattended_run() -> None:
    client = _mock_client(qualifies=True)
    candidates = {"AAA": PhasePrices(x=10, y=12, z=15, w=13, v=11)}
    result = screen_candidates(client, candidates, Season.BUY)
    assert result == ["AAA"]
