"""Pick the architectural style to use for a given repository.

Resolution policy (plan F1.4):

    1. If a valid `.architecture.yaml` is present, trust it.
       The heuristic detector still runs for divergence reporting.
    2. Otherwise, run the heuristic detector. If confidence >= 0.8 and the
       style is not 'universal', adopt it.
    3. Otherwise, fall back to 'universal' rules.

The resolver also surfaces a `divergence_warning` when an explicit declaration
disagrees significantly with the heuristic — useful for the bot to publish a
non-blocking informational comment (see plan section 9 — "Estilo declarado ≠
estilo real").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from arch_guardian_engine.config.loader import (
    ArchitectureProfile,
    ConfigError,
    Style,
    load_profile,
)
from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.style_detector import DetectionResult, detect_style

_log = get_logger(__name__)

DEFAULT_CONFIG_FILENAME = ".architecture.yaml"
HIGH_CONFIDENCE_THRESHOLD = 0.8
DIVERGENCE_THRESHOLD = 0.7  # heuristic confidence at which divergence is loud


class ResolutionSource(StrEnum):
    DECLARED = "declared"
    DETECTED = "detected"
    FALLBACK_UNIVERSAL = "fallback_universal"


@dataclass(frozen=True)
class ResolvedStyle:
    """Final decision plus the trail that led to it."""

    style: Style
    source: ResolutionSource
    confidence: float
    profile: ArchitectureProfile | None
    detection: DetectionResult | None
    divergence_warning: str | None = None


def _check_divergence(declared: Style, detection: DetectionResult) -> str | None:
    """Return a warning message if the declared style disagrees with detection."""
    if detection.style == declared or detection.style == Style.UNIVERSAL:
        return None
    if detection.confidence < DIVERGENCE_THRESHOLD:
        return None
    return (
        f"Declared style '{declared.value}' disagrees with heuristic detection "
        f"'{detection.style.value}' (confidence {detection.confidence:.2f}). "
        "Review the repository layout or update .architecture.yaml."
    )


def resolve_style(
    repo_root: str | Path,
    *,
    config_filename: str = DEFAULT_CONFIG_FILENAME,
) -> ResolvedStyle:
    """Resolve the style for a repository following the F1.4 policy."""
    root = Path(repo_root).resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"repo_root does not exist: {root}")

    config_path = root / config_filename
    detection = detect_style(root)

    # Camino A — explicit declaration.
    if config_path.exists():
        try:
            profile = load_profile(config_path)
        except ConfigError as exc:
            _log.warning("architecture_yaml_invalid", path=str(config_path), error=str(exc))
            # Treat an invalid file as if it did not exist so the engine still
            # has *some* analysis to run, but record the failure prominently.
            return ResolvedStyle(
                style=detection.style if detection.is_confident else Style.UNIVERSAL,
                source=ResolutionSource.DETECTED
                if detection.is_confident
                else ResolutionSource.FALLBACK_UNIVERSAL,
                confidence=detection.confidence if detection.is_confident else 0.0,
                profile=None,
                detection=detection,
                divergence_warning=f"invalid .architecture.yaml: {exc}",
            )

        declared = profile.architecture.style
        warning = _check_divergence(declared, detection)
        _log.info(
            "style_resolved_declared",
            style=declared.value,
            detected=detection.style.value,
            detection_confidence=round(detection.confidence, 3),
            divergence=bool(warning),
        )
        return ResolvedStyle(
            style=declared,
            source=ResolutionSource.DECLARED,
            confidence=1.0,
            profile=profile,
            detection=detection,
            divergence_warning=warning,
        )

    # Camino B — high-confidence heuristic.
    if detection.confidence >= HIGH_CONFIDENCE_THRESHOLD and detection.style != Style.UNIVERSAL:
        _log.info(
            "style_resolved_detected",
            style=detection.style.value,
            confidence=round(detection.confidence, 3),
        )
        return ResolvedStyle(
            style=detection.style,
            source=ResolutionSource.DETECTED,
            confidence=detection.confidence,
            profile=None,
            detection=detection,
        )

    # Camino C — fallback to universal rules.
    _log.warning(
        "style_fallback_universal",
        detected=detection.style.value,
        confidence=round(detection.confidence, 3),
    )
    return ResolvedStyle(
        style=Style.UNIVERSAL,
        source=ResolutionSource.FALLBACK_UNIVERSAL,
        confidence=detection.confidence,
        profile=None,
        detection=detection,
    )
