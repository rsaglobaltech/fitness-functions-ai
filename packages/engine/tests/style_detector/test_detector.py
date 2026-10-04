"""Tests for the heuristic style detector against synthetic fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.config import Style
from arch_guardian_engine.style_detector import detect_style

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("hexagonal_repo", Style.HEXAGONAL),
        ("mvc_repo", Style.MVC),
        ("microservices_repo", Style.MICROSERVICES),
        ("modular_monolith_repo", Style.MODULAR_MONOLITH),
        ("fsd_repo", Style.FEATURE_SLICED_DESIGN),
    ],
)
def test_detector_identifies_style(fixture: str, expected: Style) -> None:
    result = detect_style(FIXTURES / fixture)
    assert result.style is expected, f"got {result.style} with evidence {result.evidence}"
    assert result.is_confident, f"expected confident result, got {result.confidence:.2f}"


@pytest.mark.unit
def test_detector_falls_back_to_universal_on_ambiguous() -> None:
    result = detect_style(FIXTURES / "ambiguous_repo")
    # Either we get UNIVERSAL straight away, or a very low-confidence winner.
    assert result.style is Style.UNIVERSAL or result.confidence < 0.8


@pytest.mark.unit
def test_detector_raises_on_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        detect_style(tmp_path / "nope")
