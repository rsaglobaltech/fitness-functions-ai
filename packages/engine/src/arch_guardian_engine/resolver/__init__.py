"""Style resolution: declarative > heuristic > universal fallback."""

from arch_guardian_engine.resolver.style_resolver import (
    ResolutionSource,
    ResolvedStyle,
    resolve_style,
)

__all__ = ["ResolutionSource", "ResolvedStyle", "resolve_style"]
