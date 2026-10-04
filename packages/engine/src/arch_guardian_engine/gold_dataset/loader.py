"""Loader for gold dataset cases."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, ValidationError

from arch_guardian_engine.logging import get_logger

_log = get_logger(__name__)


class Label(StrEnum):
    VIOLATION = "violation"
    CLEAN = "clean"
    AMBIGUOUS = "ambiguous"


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class InvalidGoldCaseError(ValueError):
    """Raised when a gold case fails schema validation."""


@dataclass(frozen=True)
class GoldCodeFile:
    path: str
    content: str


@dataclass(frozen=True)
class GoldSource:
    origin: str
    reference: str | None = None


@dataclass(frozen=True)
class GoldCase:
    id: str
    style: str
    language: str
    label: Label
    code: tuple[GoldCodeFile, ...]
    rationale: str
    source: GoldSource
    rule_id: str | None = None
    severity: Severity | None = None
    tags: tuple[str, ...] = ()
    added_at: str | None = None


@dataclass(frozen=True)
class GoldDataset:
    name: str
    version: str
    cases: tuple[GoldCase, ...]

    def by_style(self, style: str) -> tuple[GoldCase, ...]:
        return tuple(c for c in self.cases if c.style == style)

    def by_label(self, label: Label) -> tuple[GoldCase, ...]:
        return tuple(c for c in self.cases if c.label == label)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    if not isinstance(loaded, dict):
        raise InvalidGoldCaseError(f"{path}: top-level must be a mapping")
    return loaded


def _build_validator(schema_path: Path) -> Draft202012Validator:
    schema = _read_yaml(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _parse_case(raw: dict[str, Any]) -> GoldCase:
    return GoldCase(
        id=raw["id"],
        style=raw["style"],
        language=raw["language"],
        label=Label(raw["label"]),
        code=tuple(GoldCodeFile(path=c["path"], content=c["content"]) for c in raw["code"]),
        rationale=raw["rationale"],
        source=GoldSource(
            origin=raw["source"]["origin"],
            reference=raw["source"].get("reference"),
        ),
        rule_id=raw.get("rule_id"),
        severity=Severity(raw["severity"]) if raw.get("severity") else None,
        tags=tuple(raw.get("tags", ())),
        added_at=raw.get("added_at"),
    )


def _iter_case_files(cases_root: Path) -> Iterable[Path]:
    yield from sorted(p for p in cases_root.rglob("*.yaml") if p.is_file())


def load_dataset(dataset_dir: str | Path) -> GoldDataset:
    """Load a gold dataset from disk.

    Args:
        dataset_dir: path to a directory containing `manifest.yaml`,
            `schema/case.schema.yaml`, and `cases/**/*.yaml`.

    Raises:
        FileNotFoundError: if any expected file is missing.
        InvalidGoldCaseError: if any case fails schema validation
            or has duplicate IDs.
    """
    root = Path(dataset_dir).resolve()
    manifest_path = root / "manifest.yaml"
    schema_path = root / "schema" / "case.schema.yaml"
    cases_root = root / "cases"

    for required in (manifest_path, schema_path, cases_root):
        if not required.exists():
            raise FileNotFoundError(f"missing required path: {required}")

    manifest = _read_yaml(manifest_path)
    validator = _build_validator(schema_path)

    cases: list[GoldCase] = []
    seen_ids: set[str] = set()

    for case_path in _iter_case_files(cases_root):
        raw = _read_yaml(case_path)
        try:
            validator.validate(raw)
        except ValidationError as exc:
            raise InvalidGoldCaseError(
                f"{case_path}: {exc.message} (at {list(exc.absolute_path)})"
            ) from exc

        case = _parse_case(raw)
        if case.id in seen_ids:
            raise InvalidGoldCaseError(f"{case_path}: duplicate case id '{case.id}'")
        seen_ids.add(case.id)
        cases.append(case)

    _log.info(
        "gold_dataset_loaded",
        dataset=manifest.get("dataset"),
        version=manifest.get("version"),
        total_cases=len(cases),
        path=str(root),
    )

    return GoldDataset(
        name=str(manifest.get("dataset", root.name)),
        version=str(manifest.get("version", "0.0.0")),
        cases=tuple(cases),
    )
