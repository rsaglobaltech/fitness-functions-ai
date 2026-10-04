"""Engine runtime settings loaded from env vars / .env."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["console", "json"]


class LLMSettings(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="GUARDIAN_LLM_")

    provider: Literal["anthropic", "azure_openai", "vllm"] = "anthropic"
    primary_model: str = "claude-sonnet-4-5"
    fallback_model: str = "claude-haiku-4-5"
    anthropic_api_key: SecretStr | None = None
    temperature: float = 0.1
    max_tokens_per_analysis: int = 4000
    budget_usd_per_pr: float = 1.0


class RAGSettings(BaseSettings):
    """Vector store + embeddings configuration."""

    model_config = SettingsConfigDict(env_prefix="GUARDIAN_RAG_")

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    embeddings_provider: Literal["voyage", "openai"] = "voyage"
    voyage_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    top_k: int = 5


class ObservabilitySettings(BaseSettings):
    """Langfuse + logging configuration."""

    model_config = SettingsConfigDict(env_prefix="GUARDIAN_OBS_")

    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "console"


class EngineSettings(BaseSettings):
    """Top-level engine settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GUARDIAN_",
        extra="ignore",
    )

    environment: Literal["development", "ci", "production"] = "development"
    workspace_root: Path = Field(default_factory=lambda: Path.cwd())
    rule_pack_cache_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "arch-guardian" / "rule-packs"
    )
    rule_pack_cache_ttl_seconds: int = 86_400  # 24h

    llm: LLMSettings = Field(default_factory=LLMSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)


def load_settings() -> EngineSettings:
    """Load and validate settings from environment + .env file."""
    return EngineSettings()
