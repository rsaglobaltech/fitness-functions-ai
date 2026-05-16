"""Thin async wrapper around the Anthropic SDK.

Responsibilities:
    - Resolve API key from settings (SecretStr) safely.
    - Apply temperature / max_tokens from settings.
    - Track usage through a BudgetGuard.
    - Emit structlog events for every call (later piped to Langfuse).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from arch_guardian_engine.llm.budget import BudgetGuard, UsageRecord
from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.settings import EngineSettings, LLMSettings, load_settings

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

_log = get_logger(__name__)


@dataclass(frozen=True)
class LLMResponse:
    """Normalized LLM response."""

    text: str
    model: str
    usage: UsageRecord
    stop_reason: str | None


class AnthropicLLMClient:
    """Async client for Anthropic Messages API."""

    def __init__(
        self,
        settings: LLMSettings,
        budget: BudgetGuard,
        *,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self._settings = settings
        self._budget = budget
        self._client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings: LLMSettings) -> AsyncAnthropic:
        from anthropic import AsyncAnthropic

        api_key = (
            settings.anthropic_api_key.get_secret_value()
            if settings.anthropic_api_key is not None
            else None
        )
        if not api_key:
            raise ValueError(
                "GUARDIAN_LLM_ANTHROPIC_API_KEY is not configured. "
                "Set it in the environment or .env file."
            )
        return AsyncAnthropic(api_key=api_key)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Run a single completion against the Anthropic Messages API."""
        chosen_model = model or self._settings.primary_model
        msg = await self._client.messages.create(
            model=chosen_model,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature if temperature is not None else self._settings.temperature,
            max_tokens=max_tokens or self._settings.max_tokens_per_analysis,
            **(extra or {}),
        )

        text_parts: list[str] = []
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        text = "".join(text_parts)
        usage = self._budget.record_and_check(
            model=chosen_model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )
        _log.info(
            "llm_call_completed",
            model=chosen_model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=round(usage.cost_usd, 6),
            stop_reason=msg.stop_reason,
        )
        return LLMResponse(
            text=text,
            model=chosen_model,
            usage=usage,
            stop_reason=msg.stop_reason,
        )


def build_default_client(
    settings: EngineSettings | None = None,
    *,
    budget: BudgetGuard | None = None,
) -> AnthropicLLMClient:
    """Build a client using EngineSettings (env / .env) and a fresh BudgetGuard."""
    s = settings or load_settings()
    guard = budget or BudgetGuard(budget_usd=s.llm.budget_usd_per_pr)
    return AnthropicLLMClient(settings=s.llm, budget=guard)
