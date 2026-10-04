"""Tests for the gold dataset loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.gold_dataset import (
    GoldDataset,
    InvalidGoldCaseError,
    Label,
    Severity,
    load_dataset,
)

DATASET_ROOT = Path(__file__).resolve().parents[3] / "catalog" / "datasets" / "gold-v1"


@pytest.mark.unit
def test_load_real_gold_dataset() -> None:
    """The committed gold-v1 dataset loads cleanly."""
    dataset = load_dataset(DATASET_ROOT)
    assert isinstance(dataset, GoldDataset)
    assert dataset.name == "gold-v1"
    assert len(dataset.cases) >= 14
    assert {c.style for c in dataset.cases} >= {"hexagonal", "mvc", "microservices", "universal"}


@pytest.mark.unit
def test_every_violation_has_rule_id_and_severity() -> None:
    """Schema invariant: violations must declare rule_id + severity."""
    dataset = load_dataset(DATASET_ROOT)
    for case in dataset.by_label(Label.VIOLATION):
        assert case.rule_id is not None, f"{case.id} missing rule_id"
        assert isinstance(case.severity, Severity), f"{case.id} missing severity"


@pytest.mark.unit
def test_no_duplicate_ids() -> None:
    """Case IDs are unique."""
    dataset = load_dataset(DATASET_ROOT)
    ids = [c.id for c in dataset.cases]
    assert len(ids) == len(set(ids))


@pytest.mark.unit
def test_invalid_case_raises(tmp_path: Path) -> None:
    """Cases that fail schema validation raise InvalidGoldCaseError."""
    # Build a minimal broken dataset on disk.
    (tmp_path / "schema").mkdir()
    (tmp_path / "cases").mkdir()
    (tmp_path / "manifest.yaml").write_text("dataset: tmp\nversion: '0.0.1'\n", encoding="utf-8")

    schema_src = DATASET_ROOT / "schema" / "case.schema.yaml"
    (tmp_path / "schema" / "case.schema.yaml").write_text(
        schema_src.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Violation with no rule_id or severity — should fail conditional schema.
    bad_case = """
id: bad-001
style: hexagonal
language: python
label: violation
code:
  - path: foo.py
    content: |
      x = 1
rationale: missing rule_id intentionally for the test
source:
  origin: synthetic
"""
    (tmp_path / "cases" / "bad.yaml").write_text(bad_case, encoding="utf-8")

    with pytest.raises(InvalidGoldCaseError):
        load_dataset(tmp_path)


@pytest.mark.unit
def test_by_style_filters() -> None:
    dataset = load_dataset(DATASET_ROOT)
    hex_cases = dataset.by_style("hexagonal")
    assert all(c.style == "hexagonal" for c in hex_cases)
    assert len(hex_cases) >= 4
