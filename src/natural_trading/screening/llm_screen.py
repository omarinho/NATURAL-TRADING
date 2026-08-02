"""REQ-003: the lunar-stock pattern check (X/Y/Z/W/V) is performed by an LLM reading
and comparing the close prices itself — this module contains zero deterministic
numeric/boolean comparison of the pattern values; the comparison happens inside the
LLM prompt/response. REQ-017: zero qualifying candidates is a valid outcome — no
exception is raised. REQ-019: invoked via the Anthropic Messages API SDK, unattended
(no interactive input at any point in this module).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from natural_trading.astro.season import Season


@dataclass(frozen=True)
class PhasePrices:
    x: float  # close on the former New Moon
    y: float  # close on the following First Quarter
    z: float  # close on the following Full Moon
    w: float  # close on the following Last Quarter
    v: float  # price on today's New Moon (the trade-open day)


class AnthropicMessagesClient(Protocol):
    def create_message(self, prompt: str) -> str: ...


SYSTEM_PROMPT = (
    "You are a precise pattern classifier for a rule-based swing trading system. "
    "You will be given five close prices from a stock's lunar cycle: X (former New "
    "Moon), Y (First Quarter), Z (Full Moon), W (Last Quarter), V (today's New Moon). "
    "Classify whether they satisfy the active season's required pattern. "
    "BUY season pattern: X<Y<Z, then Z>W, then W>V. "
    "SELL season pattern: X>Y>Z, then Z<W, then W<V. "
    "Think step by step: explicitly verify each comparison in order before concluding "
    "— do not jump straight to an answer, an instant unreasoned answer on this kind of "
    "chained comparison is frequently wrong even when the numbers are unambiguous. "
    "After your reasoning, end your response with a final line containing only a JSON "
    'object in exactly this form: {"qualifies": true} or {"qualifies": false}.'
)

# Matches the final {"qualifies": true/false} object wherever it appears in the
# response — reasoning text and/or markdown code fences may precede or surround it,
# since the model is asked to show its work first (see SYSTEM_PROMPT above) rather
# than forced into an instant bare-JSON answer.
_QUALIFIES_PATTERN = re.compile(r'\{\s*"qualifies"\s*:\s*(true|false)\s*\}')


def _build_prompt(symbol: str, prices: PhasePrices, season: Season) -> str:
    return (
        f"Symbol: {symbol}\n"
        f"Season: {season.value}\n"
        f"X={prices.x} Y={prices.y} Z={prices.z} W={prices.w} V={prices.v}\n"
        "Does this candidate qualify as a lunar stock for the active season's pattern?"
    )


def screen_candidate(
    client: AnthropicMessagesClient,
    symbol: str,
    prices: PhasePrices,
    season: Season,
) -> bool:
    """Builds the prompt, invokes the Messages API, and parses the yes/no verdict — no
    numeric/boolean comparison of `prices` happens in this function."""
    prompt = _build_prompt(symbol, prices, season)
    raw_response = client.create_message(prompt)
    match = _QUALIFIES_PATTERN.search(raw_response)
    if match is None:
        return False
    return match.group(1) == "true"


def screen_candidates(
    client: AnthropicMessagesClient,
    candidates: dict[str, PhasePrices],
    season: Season,
) -> list[str]:
    """REQ-017: an empty result is a valid, non-error outcome."""
    return [
        symbol
        for symbol, prices in candidates.items()
        if screen_candidate(client, symbol, prices, season)
    ]
