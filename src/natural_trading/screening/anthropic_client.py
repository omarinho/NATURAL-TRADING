"""Live `AnthropicMessagesClient` implementation — REQ-019: invoked via the official
anthropic Python SDK's Messages API, no human-in-the-loop step."""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic

from natural_trading.config import DEFAULT_ANTHROPIC_MODEL
from natural_trading.screening.llm_screen import SYSTEM_PROMPT

# Re-exported from config.py, the single source of truth for this default — main.py
# always passes anthropic.input's configured model explicitly, so this only matters
# for a caller that constructs LiveAnthropicClient directly without specifying one
# (e.g. a test).
DEFAULT_MODEL = DEFAULT_ANTHROPIC_MODEL
# The model is asked to reason step-by-step before its final JSON verdict (see
# llm_screen.SYSTEM_PROMPT) — 200 tokens was enough for a bare JSON answer but cuts
# off a full reasoning trace before the final line, which would make
# _QUALIFIES_PATTERN find no match and silently default to False.
DEFAULT_MAX_TOKENS = 1024


@dataclass
class LiveAnthropicClient:
    api_key: str
    model: str = DEFAULT_MODEL
    _client: anthropic.Anthropic = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=self.api_key)

    def create_message(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        # Confirmed empirically against the real API: claude-sonnet-5 returns
        # extended thinking as a leading content block (a ThinkingBlock, no .text
        # attribute — only an opaque .thinking field), with the actual answer in a
        # later TextBlock. Reading content[0] unconditionally would silently return
        # the thinking block's stringified repr instead of the real verdict text.
        for block in response.content:
            if hasattr(block, "text"):
                return str(block.text)
        return ""
