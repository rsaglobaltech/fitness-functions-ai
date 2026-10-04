"""Tests for the LLM budget guard."""

from __future__ import annotations

import pytest
from arch_guardian_engine.llm.budget import (
    BudgetExceededError,
    BudgetGuard,
    estimate_cost_usd,
)


@pytest.mark.unit
def test_estimate_cost_sonnet() -> None:
    cost = estimate_cost_usd("claude-sonnet-4-5", 1_000_000, 1_000_000)
    # $3 + $15 = $18 for 1M in + 1M out
    assert cost == pytest.approx(18.0)


@pytest.mark.unit
def test_estimate_cost_unknown_model_uses_sonnet_pricing() -> None:
    cost = estimate_cost_usd("unknown-model", 1_000_000, 0)
    assert cost == pytest.approx(3.0)


@pytest.mark.unit
def test_budget_records_usage() -> None:
    guard = BudgetGuard(budget_usd=1.0)
    rec = guard.record_and_check("claude-haiku-4-5", 1_000, 500)
    assert rec.input_tokens == 1_000
    assert rec.output_tokens == 500
    assert guard.total_cost_usd > 0
    assert len(guard.records) == 1


@pytest.mark.unit
def test_budget_raises_when_exceeded() -> None:
    guard = BudgetGuard(budget_usd=0.001)
    with pytest.raises(BudgetExceededError):
        guard.record_and_check("claude-sonnet-4-5", 1_000_000, 0)


@pytest.mark.unit
def test_budget_cumulative_across_calls() -> None:
    guard = BudgetGuard(budget_usd=0.01)
    # Each call below the cap, but cumulative crosses it.
    guard.record_and_check("claude-haiku-4-5", 5_000, 1_000)
    with pytest.raises(BudgetExceededError):
        for _ in range(50):
            guard.record_and_check("claude-haiku-4-5", 5_000, 1_000)
    assert guard.total_cost_usd > 0.01
