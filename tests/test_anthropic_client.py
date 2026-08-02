"""Covers LiveAnthropicClient.create_message()'s content-block extraction. Confirmed
empirically against the real Anthropic Messages API: claude-sonnet-5 returns extended
thinking as a leading content block — response.content[0] is a ThinkingBlock with no
usable .text (only an opaque .thinking field), and the real answer (with the
{"qualifies": ...} JSON llm_screen.py's regex looks for) is in a later TextBlock.
create_message() must find that block regardless of position, not always read
content[0] — reading content[0] blindly silently discards the real verdict and makes
_QUALIFIES_PATTERN find nothing, defaulting every candidate to not-qualifying."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from natural_trading.screening.anthropic_client import LiveAnthropicClient


def _thinking_block() -> SimpleNamespace:
    return SimpleNamespace(type="thinking", thinking="")


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


@patch("anthropic.Anthropic")
def test_create_message_returns_text_block_when_it_is_the_only_block(
    mock_anthropic_cls: MagicMock,
) -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[_text_block('{"qualifies": true}')]
    )
    mock_anthropic_cls.return_value = mock_client

    client = LiveAnthropicClient(api_key="fake-key")
    result = client.create_message("some prompt")

    assert result == '{"qualifies": true}'


@patch("anthropic.Anthropic")
def test_create_message_skips_leading_thinking_block_to_find_the_real_text(
    mock_anthropic_cls: MagicMock,
) -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[_thinking_block(), _text_block('{"qualifies": false}')]
    )
    mock_anthropic_cls.return_value = mock_client

    client = LiveAnthropicClient(api_key="fake-key")
    result = client.create_message("some prompt")

    assert result == '{"qualifies": false}'
