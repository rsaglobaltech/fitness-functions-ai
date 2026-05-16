"""Per-PR budget guard for LLM calls.

Cuts off LLM usage when the cumulative cost in a single analysis exceeds the
configured budget (default $1 USD per PR — see plan F3.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from arch_guardian_engine.logging import get_logger

_log = get_logger(__name__)


class BudgetExceededError(RuntimeError):
    """Raised when the cumulative LLM cost surpasses the configured budget."""


# Pricing per 1M tokens (USD). Kept here because we want a single source of truth
# that does not require a network call. Update when Anthropic publishes new prices.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # model: (input, output)
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "claude-opus-4-7": (15.0, 75.0),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a single LLM call."""
    in_price, out_price = _PRICE_PER_MTOK.get(model, (3.0, 15.0))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000.0


@dataclass(frozen=True)
class UsageRecord:
    """One LLM call accounting entry."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class BudgetGuard:
    """Tracks cumulative spend and aborts when the cap is reached."""

    budget_usd: float
    records: list[UsageRecord] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    def record_and_check(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> UsageRecord:
        """Record a usage entry and raise if the budget is exceeded."""
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        record = UsageRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        with self._lock:
            self.records.append(record)
            total = sum(r.cost_usd for r in self.records)
        _log.debug(
            "llm_usage_recorded",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            cumulative_cost_usd=round(total, 6),
        )
        if total > self.budget_usd:
            raise BudgetExceededError(
                f"LLM budget of ${self.budget_usd:.2f} exceeded "
                f"(spent ${total:.4f} over {len(self.records)} calls)"
            )
        return record
