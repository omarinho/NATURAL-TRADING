"""Live `AnthropicMessagesClient` implementation — REQ-019: invoked via the official
anthropic Python SDK's Messages API, no human-in-the-loop step."""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic

from natural_trading.screening.llm_screen import SYSTEM_PROMPT

DEFAULT_MODEL = "claude-sonnet-4-5"
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
        block = response.content[0]
        return block.text if hasattr(block, "text") else str(block)
