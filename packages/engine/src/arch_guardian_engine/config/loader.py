"""Pydantic-typed loader for `.architecture.yaml`.

Validation flow:
    YAML --> JSON Schema (strict structural rules)
         --> Pydantic models (typed access)
         --> ArchitectureProfile (final immutable view)

The schema and Pydantic models are kept in sync but serve different roles:
    - The JSON Schema is the *contract* exposed to users and external tooling.
    - The Pydantic models are the *internal API* used throughout the engine.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, ValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from arch_guardian_engine.logging import get_logger

_log = get_logger(__name__)

# Resolve catalog schema relative to this file. Layout:
#   packages/engine/src/arch_guardian_engine/config/loader.py  (this file)
#   packages/catalog/schema/architecture_yaml_v1.json          (target)
DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[4] / "catalog" / "schema" / "architecture_yaml_v1.json"
)


class ConfigError(ValueError):
    """Raised when `.architecture.yaml` fails to load or validate."""


class Style(StrEnum):
    HEXAGONAL = "hexagonal"
    LAYERED = "layered"
    MVC = "mvc"
    MICROSERVICES = "microservices"
    EVENT_DRIVEN_CQRS = "event_driven_cqrs"
    MODULAR_MONOLITH = "modular_monolith"
    VERTICAL_SLICE = "vertical_slice"
    FEATURE_SLICED_DESIGN = "feature_sliced_design"
    DDD = "ddd"
    PLUGIN_MICROKERNEL = "plugin_microkernel"
    PIPES_FILTERS = "pipes_filters"
    UNIVERSAL = "universal"


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"
    OFF = "off"


class ProjectSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    language: str
    runtime: str | None = None


class ArchitectureSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    style: Style
    rule_pack_version: str
    strict_mode: bool = False

    @field_validator("rule_pack_version")
    @classmethod
    def _validate_semver(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[0-9]+(\.[0-9]+){0,2}(\.[xX])?", value):
            raise ValueError(
                f"rule_pack_version must look like '2.3.0', '2.3.x' or '2.x'; got '{value}'"
            )
        return value


class GodObjectThreshold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: Severity = Severity.WARNING
    max_methods: int = Field(default=25, ge=1)
    max_loc: int = Field(default=500, ge=1)


class CyclomaticComplexityRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: Severity = Severity.WARNING
    max_per_function: int = Field(default=15, ge=1)


class UniversalRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    circular_dependencies: Severity = Severity.CRITICAL
    god_object_threshold: GodObjectThreshold = Field(default_factory=GodObjectThreshold)
    cyclomatic_complexity: CyclomaticComplexityRule = Field(
        default_factory=CyclomaticComplexityRule
    )
    mutable_global_state: Severity = Severity.WARNING


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adr_path: str | None = None
    conventions_path: str | None = None
    exclude_patterns: tuple[str, ...] = ()


class ExceptionRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    reason: str = Field(min_length=5)
    expires: str | None = None
    suppress_rules: tuple[str, ...] = ()


class ArchitectureProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    project: ProjectSection
    architecture: ArchitectureSection
    layout: dict[str, Any] = Field(default_factory=dict)
    universal_rules: UniversalRules = Field(default_factory=UniversalRules)
    knowledge_base: KnowledgeBase = Field(default_factory=KnowledgeBase)
    exceptions: tuple[ExceptionRule, ...] = ()


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: file not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML — {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path}: top-level must be a mapping")
    return loaded


def _load_schema(schema_path: Path) -> Draft202012Validator:
    if not schema_path.exists():
        raise ConfigError(f"schema not found at {schema_path}")
    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _format_error(error: ValidationError) -> str:
    location = "/".join(str(part) for part in error.absolute_path) or "<root>"
    return f"at '{location}': {error.message}"


def _validate(raw: dict[str, Any], schema_path: Path) -> None:
    validator = _load_schema(schema_path)
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if errors:
        joined = "\n  - ".join(_format_error(e) for e in errors)
        raise ConfigError(f".architecture.yaml failed schema validation:\n  - {joined}")


def load_profile(
    path: str | Path,
    *,
    schema_path: Path | None = None,
) -> ArchitectureProfile:
    """Load and validate a `.architecture.yaml` file from disk."""
    yaml_path = Path(path).resolve()
    raw = _read_yaml(yaml_path)
    _validate(raw, schema_path or DEFAULT_SCHEMA_PATH)
    profile = ArchitectureProfile.model_validate(raw)
    _log.info(
        "architecture_profile_loaded",
        path=str(yaml_path),
        style=profile.architecture.style.value,
        language=profile.project.language,
        rule_pack_version=profile.architecture.rule_pack_version,
    )
    return profile


def load_profile_from_string(
    yaml_text: str,
    *,
    schema_path: Path | None = None,
) -> ArchitectureProfile:
    """Load a profile from a YAML string (handy for tests + CLI piping)."""
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("top-level must be a mapping")
    _validate(raw, schema_path or DEFAULT_SCHEMA_PATH)
    return ArchitectureProfile.model_validate(raw)
