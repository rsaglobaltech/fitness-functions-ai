"""Tests for engine settings loading."""

from __future__ import annotations

import pytest
from arch_guardian_engine.settings import EngineSettings, load_settings

_GUARDIAN_ENV_PREFIXES = ("GUARDIAN_",)


@pytest.fixture(autouse=True)
def _isolate_guardian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any GUARDIAN_* env vars that may leak from the host or CI."""
    import os

    for key in list(os.environ):
        if any(key.startswith(p) for p in _GUARDIAN_ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)


@pytest.mark.unit
def test_load_settings_defaults() -> None:
    """Default settings load without env vars and have sane defaults."""
    settings = load_settings()
    assert isinstance(settings, EngineSettings)
    assert settings.environment == "development"
    assert settings.llm.primary_model == "claude-sonnet-4-5"
    assert settings.llm.temperature == 0.1
    assert settings.observability.log_level == "INFO"
    assert settings.rule_pack_cache_ttl_seconds == 86_400


@pytest.mark.unit
def test_load_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables override defaults."""
    monkeypatch.setenv("GUARDIAN_ENVIRONMENT", "production")
    monkeypatch.setenv("GUARDIAN_LLM_PRIMARY_MODEL", "claude-opus-4-7")
    monkeypatch.setenv("GUARDIAN_OBS_LOG_LEVEL", "DEBUG")

    settings = load_settings()
    assert settings.environment == "production"
    assert settings.llm.primary_model == "claude-opus-4-7"
    assert settings.observability.log_level == "DEBUG"


@pytest.mark.unit
def test_llm_budget_default_is_one_usd() -> None:
    """Budget guard default is $1 USD per PR (see plan F3.6)."""
    settings = load_settings()
    assert settings.llm.budget_usd_per_pr == 1.0
