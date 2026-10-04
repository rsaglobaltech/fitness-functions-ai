"""Tests for the Anthropic LLM client (with a fake SDK)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from arch_guardian_engine.llm.anthropic_client import AnthropicLLMClient
from arch_guardian_engine.llm.budget import BudgetExceededError, BudgetGuard
from arch_guardian_engine.settings import LLMSettings
from pydantic import SecretStr


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeBlock:
    type: str
    text: str


@dataclass
class _FakeMessage:
    content: list[_FakeBlock]
    usage: _FakeUsage
    stop_reason: str = "end_turn"


class _FakeMessages:
    def __init__(self, response: _FakeMessage) -> None:
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _FakeMessage:
        self.last_kwargs = kwargs
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: _FakeMessage) -> None:
        self.messages = _FakeMessages(response)


def _client(
    response: _FakeMessage, *, budget_usd: float = 1.0
) -> tuple[AnthropicLLMClient, BudgetGuard, _FakeAnthropicClient]:
    settings = LLMSettings(anthropic_api_key=SecretStr("test-key"))
    guard = BudgetGuard(budget_usd=budget_usd)
    fake = _FakeAnthropicClient(response)
    client = AnthropicLLMClient(settings=settings, budget=guard, client=fake)  # type: ignore[arg-type]
    return client, guard, fake


@pytest.mark.unit
async def test_complete_returns_text_and_records_usage() -> None:
    response = _FakeMessage(
        content=[_FakeBlock(type="text", text="ok")],
        usage=_FakeUsage(input_tokens=10, output_tokens=20),
    )
    client, guard, fake = _client(response)

    result = await client.complete(system="sys", user="hi")
    assert result.text == "ok"
    assert result.model == "claude-sonnet-4-5"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 20
    assert len(guard.records) == 1
    assert fake.messages.last_kwargs is not None
    assert fake.messages.last_kwargs["temperature"] == 0.1


@pytest.mark.unit
async def test_complete_raises_when_budget_exceeded() -> None:
    response = _FakeMessage(
        content=[_FakeBlock(type="text", text="x")],
        usage=_FakeUsage(input_tokens=10_000_000, output_tokens=0),
    )
    client, _, _ = _client(response, budget_usd=0.0001)
    with pytest.raises(BudgetExceededError):
        await client.complete(system="sys", user="hi")


@pytest.mark.unit
def test_missing_api_key_raises() -> None:
    settings = LLMSettings(anthropic_api_key=None)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicLLMClient(settings=settings, budget=BudgetGuard(budget_usd=1.0))
