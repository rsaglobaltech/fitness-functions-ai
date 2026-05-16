"""Tests for the .architecture.yaml loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.config import (
    ConfigError,
    Severity,
    Style,
    load_profile,
    load_profile_from_string,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HEX_YAML = FIXTURES / "hexagonal_repo" / ".architecture.yaml"


@pytest.mark.unit
def test_load_hexagonal_fixture() -> None:
    profile = load_profile(HEX_YAML)
    assert profile.schema_version == "1.0"
    assert profile.project.language == "typescript"
    assert profile.architecture.style is Style.HEXAGONAL
    assert profile.architecture.rule_pack_version == "1.0.0"
    assert profile.architecture.strict_mode is True
    assert "layers" in profile.layout


@pytest.mark.unit
def test_unknown_style_rejected() -> None:
    bad = """
schema_version: "1.0"
project:
  name: x
  language: python
architecture:
  style: not-a-style
  rule_pack_version: "1.0.0"
"""
    with pytest.raises(ConfigError, match="schema validation"):
        load_profile_from_string(bad)


@pytest.mark.unit
def test_bad_rule_pack_version_rejected() -> None:
    bad = """
schema_version: "1.0"
project:
  name: x
  language: python
architecture:
  style: mvc
  rule_pack_version: "not_semver"
"""
    with pytest.raises(ConfigError):
        load_profile_from_string(bad)


@pytest.mark.unit
def test_universal_rules_defaults() -> None:
    minimal = """
schema_version: "1.0"
project:
  name: x
  language: python
architecture:
  style: universal
  rule_pack_version: "1.x"
"""
    profile = load_profile_from_string(minimal)
    assert profile.universal_rules.circular_dependencies == Severity.CRITICAL
    assert profile.universal_rules.god_object_threshold.max_methods == 25
    assert profile.universal_rules.cyclomatic_complexity.max_per_function == 15


@pytest.mark.unit
def test_unknown_top_level_key_rejected() -> None:
    bad = """
schema_version: "1.0"
project:
  name: x
  language: python
architecture:
  style: mvc
  rule_pack_version: "1.0.0"
unexpected_field: 42
"""
    with pytest.raises(ConfigError, match="Additional properties"):
        load_profile_from_string(bad)


@pytest.mark.unit
def test_exception_requires_reason() -> None:
    bad = """
schema_version: "1.0"
project:
  name: x
  language: python
architecture:
  style: mvc
  rule_pack_version: "1.0.0"
exceptions:
  - path: "legacy/**"
"""
    with pytest.raises(ConfigError):
        load_profile_from_string(bad)


@pytest.mark.unit
def test_load_profile_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_profile(tmp_path / "does-not-exist.yaml")


@pytest.mark.unit
def test_load_profile_invalid_yaml(tmp_path: Path) -> None:
    p = tmp_path / "x.yaml"
    p.write_text(":\n :\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_profile(p)
