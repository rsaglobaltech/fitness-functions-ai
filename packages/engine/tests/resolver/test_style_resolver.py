"""Tests for the style resolver (camino A / B / C)."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.config import Style
from arch_guardian_engine.resolver import ResolutionSource, resolve_style

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.unit
def test_camino_a_declared_file_is_trusted() -> None:
    """Repo with valid .architecture.yaml → DECLARED, confidence 1.0."""
    result = resolve_style(FIXTURES / "hexagonal_repo")
    assert result.source is ResolutionSource.DECLARED
    assert result.style is Style.HEXAGONAL
    assert result.confidence == 1.0
    assert result.profile is not None
    assert result.detection is not None
    # Detector should also have run and agreed.
    assert result.detection.style is Style.HEXAGONAL
    assert result.divergence_warning is None


@pytest.mark.unit
def test_camino_b_heuristic_high_confidence() -> None:
    """Repo without .architecture.yaml but clear MVC layout → DETECTED."""
    result = resolve_style(FIXTURES / "mvc_repo")
    assert result.source is ResolutionSource.DETECTED
    assert result.style is Style.MVC
    assert result.confidence >= 0.8
    assert result.profile is None


@pytest.mark.unit
def test_camino_c_universal_fallback() -> None:
    """Ambiguous repo → FALLBACK_UNIVERSAL."""
    result = resolve_style(FIXTURES / "ambiguous_repo")
    assert result.source is ResolutionSource.FALLBACK_UNIVERSAL
    assert result.style is Style.UNIVERSAL


@pytest.mark.unit
def test_invalid_yaml_falls_back_with_warning(tmp_path: Path) -> None:
    """Broken .architecture.yaml → resolver falls back AND records warning."""
    repo = tmp_path / "broken_repo"
    repo.mkdir()
    (repo / "src" / "controllers").mkdir(parents=True)
    (repo / "src" / "controllers" / "x.py").write_text("x = 1\n")
    (repo / "src" / "views").mkdir()
    (repo / "src" / "views" / "y.py").write_text("y = 1\n")
    (repo / "src" / "models").mkdir()
    (repo / "src" / "models" / "z.py").write_text("z = 1\n")
    (repo / ".architecture.yaml").write_text("not: [valid", encoding="utf-8")

    result = resolve_style(repo)
    assert result.divergence_warning is not None
    assert "invalid" in result.divergence_warning.lower()
    assert result.profile is None


@pytest.mark.unit
def test_divergence_warning_when_declared_disagrees_with_detection(
    tmp_path: Path,
) -> None:
    """Repo declares MVC but its layout shouts Hexagonal → warning surfaces."""
    repo = tmp_path / "diverging_repo"
    (repo / "src" / "domain" / "ports").mkdir(parents=True)
    (repo / "src" / "domain" / "ports" / "p.ts").write_text("export interface P {}\n")
    (repo / "src" / "application").mkdir()
    (repo / "src" / "application" / "u.ts").write_text("export const u = 1;\n")
    (repo / "src" / "infrastructure").mkdir()
    (repo / "src" / "infrastructure" / "a.ts").write_text("export const a = 1;\n")
    (repo / ".architecture.yaml").write_text(
        """
schema_version: "1.0"
project:
  name: diverging
  language: typescript
architecture:
  style: mvc
  rule_pack_version: "1.0.0"
""",
        encoding="utf-8",
    )

    result = resolve_style(repo)
    assert result.source is ResolutionSource.DECLARED
    assert result.style is Style.MVC  # we still trust the declaration
    assert result.divergence_warning is not None
    assert "hexagonal" in result.divergence_warning.lower()


@pytest.mark.unit
def test_resolve_missing_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_style(tmp_path / "nope")
