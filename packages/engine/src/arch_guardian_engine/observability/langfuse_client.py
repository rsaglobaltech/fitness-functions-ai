"""Langfuse tracing wrapper.

The engine emits trace events at key points (per-PR analysis, per-LLM-call).
Langfuse is optional: if credentials are missing the NullTracer is used and the
engine continues without observability — useful for local dev / CI.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Protocol

from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.settings import EngineSettings, ObservabilitySettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

_log = get_logger(__name__)


class Tracer(Protocol):
    """Minimal tracer interface used by the engine."""

    @contextmanager
    def trace(self, name: str, **metadata: Any) -> Iterator[None]: ...

    def log_generation(
        self,
        *,
        name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def flush(self) -> None: ...


class NullTracer:
    """No-op tracer used when Langfuse credentials are not configured."""

    @contextmanager
    def trace(self, name: str, **metadata: Any) -> Iterator[None]:
        _log.debug("trace_noop", name=name, **metadata)
        yield

    def log_generation(
        self,
        *,
        name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        _log.debug(
            "generation_noop",
            name=name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

    def flush(self) -> None:
        return None


class LangfuseTracer:
    """Tracer backed by the Langfuse client."""

    def __init__(self, settings: ObservabilitySettings) -> None:
        from langfuse import Langfuse

        public = (
            settings.langfuse_public_key.get_secret_value()
            if settings.langfuse_public_key
            else None
        )
        secret = (
            settings.langfuse_secret_key.get_secret_value()
            if settings.langfuse_secret_key
            else None
        )
        if not public or not secret:
            raise ValueError("Langfuse keys missing — use NullTracer instead.")
        self._client = Langfuse(
            public_key=public,
            secret_key=secret,
            host=settings.langfuse_host,
        )

    @contextmanager
    def trace(self, name: str, **metadata: Any) -> Iterator[None]:
        trace = self._client.trace(name=name, metadata=metadata or None)
        try:
            yield
        except Exception as exc:
            trace.update(status_message=f"error: {exc!r}", level="ERROR")
            raise
        finally:
            self._client.flush()

    def log_generation(
        self,
        *,
        name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._client.generation(
            name=name,
            model=model,
            usage={
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
                "unit": "TOKENS",
            },
            metadata={"cost_usd": cost_usd, **(metadata or {})},
        )

    def flush(self) -> None:
        self._client.flush()


def build_tracer(settings: EngineSettings | None = None) -> Tracer:
    """Return Langfuse tracer if configured, otherwise NullTracer."""
    s = settings or load_settings()
    obs = s.observability
    if obs.langfuse_public_key and obs.langfuse_secret_key:
        try:
            return LangfuseTracer(obs)
        except Exception as exc:
            _log.warning("langfuse_init_failed", error=repr(exc))
    return NullTracer()
