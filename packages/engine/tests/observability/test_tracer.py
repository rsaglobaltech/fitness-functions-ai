"""Tests for the tracer factory and NullTracer."""

from __future__ import annotations

import pytest
from arch_guardian_engine.observability import NullTracer, build_tracer
from arch_guardian_engine.settings import EngineSettings


@pytest.fixture(autouse=True)
def _isolate_guardian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("GUARDIAN_"):
            monkeypatch.delenv(key, raising=False)


@pytest.mark.unit
def test_build_tracer_returns_null_when_no_keys() -> None:
    tracer = build_tracer(EngineSettings())
    assert isinstance(tracer, NullTracer)


@pytest.mark.unit
def test_null_tracer_context_manager_is_noop() -> None:
    tracer = NullTracer()
    with tracer.trace("test-analysis", pr_id="42"):
        tracer.log_generation(
            name="violation_analysis",
            model="claude-sonnet-4-5",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0001,
        )
    tracer.flush()  # must not raise
