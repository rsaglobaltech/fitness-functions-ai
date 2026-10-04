"""Layer dependency rules end-to-end through RepositoryAnalyzer."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.analyzer import (
    ChangeAnalysisRequest,
    RepositoryAnalyzer,
    analyze_changes,
)
from arch_guardian_engine.config import ConfigError, Severity, Style
from arch_guardian_engine.findings import AnalysisReport, Finding
from arch_guardian_engine.rules import parse_layers

from tests.conftest import GitRepo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

HEX_LAYOUT = """\
layout:
  layers:
    domain:
      paths: ["src/domain/**"]
      can_depend_on: []
      forbidden_imports: ["@prisma/*", "sqlalchemy"]
    ports:
      paths: ["src/domain/ports/**"]
      can_depend_on: ["domain"]
    application:
      paths: ["src/application/**"]
      can_depend_on: ["domain", "ports"]
    infrastructure:
      paths: ["src/infrastructure/**"]
      can_depend_on: ["domain", "ports", "application"]
"""


def _yaml(style: str = "hexagonal", strict: bool = True, body: str = HEX_LAYOUT) -> str:
    return (
        'schema_version: "1.0"\n'
        "project:\n  name: t\n  language: typescript\n"
        f'architecture:\n  style: {style}\n  rule_pack_version: "1.0.0"\n'
        f"  strict_mode: {'true' if strict else 'false'}\n" + body
    )


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _layer_findings(report: AnalysisReport) -> list[Finding]:
    return [f for f in report.findings if f.rule_id.endswith(".layer_violation")]


HEX_FILES = {
    "src/domain/Order.ts": (
        'import { PrismaClient } from "@prisma/client";\n'
        'import { Db } from "../infrastructure/Db";\n'
        'import { Db as Again } from "../infrastructure/Db";\n'
        "export class Order {}\n"
    ),
    "src/domain/ports/OrderRepo.ts": 'import { Order } from "../Order";\n',
    "src/application/CreateOrder.ts": (
        'import { OrderRepo } from "../domain/ports/OrderRepo";\n'
        'import { log } from "../shared/log";\n'
    ),
    "src/infrastructure/Db.ts": 'import { CreateOrder } from "../application/CreateOrder";\n',
    "src/shared/log.ts": 'import { Db } from "../infrastructure/Db";\n',
}


@pytest.mark.integration
def test_hexagonal_internal_and_external_violations(tmp_path: Path) -> None:
    _write(tmp_path, {".architecture.yaml": _yaml(), **HEX_FILES})
    findings = _layer_findings(RepositoryAnalyzer().analyze(tmp_path))

    summary = sorted((f.location.file, f.location.line, f.metadata["kind"]) for f in findings)
    assert summary == [
        ("src/domain/Order.ts", 1, "external"),
        ("src/domain/Order.ts", 2, "internal"),  # one finding for two imports, first line
    ]
    internal = next(f for f in findings if f.metadata["kind"] == "internal")
    assert internal.rule_id == "hexagonal.layer_violation"
    assert internal.severity is Severity.CRITICAL
    assert internal.rule_pack == "hexagonal@1.0.0"
    assert internal.metadata["to_layer"] == "infrastructure"


@pytest.mark.integration
def test_most_specific_layer_wins(tmp_path: Path) -> None:
    # ports (more specific than domain/**) may import domain; domain may not import ports.
    _write(
        tmp_path,
        {
            ".architecture.yaml": _yaml(),
            "src/domain/ports/Repo.ts": 'import { O } from "../O";\n',
            "src/domain/O.ts": 'import { Repo } from "./ports/Repo";\n',
        },
    )
    findings = _layer_findings(RepositoryAnalyzer().analyze(tmp_path))
    assert [(f.location.file, f.metadata["to_layer"]) for f in findings] == [
        ("src/domain/O.ts", "ports")
    ]


@pytest.mark.integration
def test_python_forbidden_import_reported_once_per_statement(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            ".architecture.yaml": _yaml(strict=False),
            "src/domain/model.py": "from sqlalchemy.orm import Session, relationship\n",
        },
    )
    findings = _layer_findings(RepositoryAnalyzer().analyze(tmp_path))
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING  # strict_mode false


@pytest.mark.integration
def test_fsd_layers_order(tmp_path: Path) -> None:
    body = (
        "layout:\n"
        "  layers_order: [shared, entities, features, pages]\n"
        "  paths:\n"
        '    shared: "src/shared/**"\n'
        '    entities: "src/entities/**"\n'
        '    features: "src/features/**"\n'
        '    pages: "src/pages/**"\n'
    )
    _write(
        tmp_path,
        {
            ".architecture.yaml": _yaml(style="feature_sliced_design", body=body),
            "src/pages/Home.tsx": 'import { SignIn } from "../features/SignIn";\n',
            "src/features/SignIn.tsx": 'import { Home } from "../pages/Home";\n',
            "src/entities/User.ts": 'import { api } from "../shared/api";\n',
            "src/shared/api.ts": "export const api = 1;\n",
        },
    )
    findings = _layer_findings(RepositoryAnalyzer().analyze(tmp_path))
    assert [(f.location.file, f.rule_id) for f in findings] == [
        ("src/features/SignIn.tsx", "feature_sliced_design.layer_violation")
    ]


@pytest.mark.integration
def test_clean_fixture_has_no_layer_findings() -> None:
    report = RepositoryAnalyzer().analyze(FIXTURES / "hexagonal_repo")
    assert report.config_error is None
    assert _layer_findings(report) == []


@pytest.mark.integration
def test_layer_violation_can_be_suppressed_by_exception(tmp_path: Path) -> None:
    body = HEX_LAYOUT + (
        "exceptions:\n"
        '  - path: "src/domain/**"\n'
        '    reason: "migrating persistence out of domain"\n'
        '    suppress_rules: ["layer_violation"]\n'
    )
    _write(tmp_path, {".architecture.yaml": _yaml(body=body), **HEX_FILES})
    report = RepositoryAnalyzer().analyze(tmp_path)
    assert _layer_findings(report) == []
    assert report.suppressed_count == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    ("layout", "message"),
    [
        ({"layers": []}, "non-empty mapping"),
        ({"layers": {"a": {"can_depend_on": []}}}, "at least one path"),
        ({"layers": {"a": {"paths": ["x/**"], "can_depend_on": ["b"]}}}, "unknown layers"),
        ({"layers": {"a": {"paths": ["x/**"], "allow": []}}}, "unknown keys"),
        ({"layers": {"a": {"paths": "x/**"}}}, "list of non-empty strings"),
    ],
)
def test_invalid_layouts_raise(layout: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_layers(Style.HEXAGONAL, layout)


@pytest.mark.unit
def test_layout_without_layers_is_none() -> None:
    assert parse_layers(Style.MVC, {"components": {}}) is None


@pytest.mark.integration
def test_invalid_layout_surfaces_as_config_error(tmp_path: Path) -> None:
    body = "layout:\n  layers:\n    domain:\n      paths: []\n"
    _write(tmp_path, {".architecture.yaml": _yaml(body=body), "src/a.ts": ""})
    report = RepositoryAnalyzer().analyze(tmp_path)
    assert report.config_error is not None
    assert "at least one path" in report.config_error


@pytest.mark.integration
def test_adopting_layers_in_a_pr_only_reports_new_violations(git_repo: GitRepo) -> None:
    _write(git_repo.root, HEX_FILES)
    git_repo.commit("existing code with violations, no config")
    git_repo.git("checkout", "-q", "-b", "feature")
    _write(
        git_repo.root,
        {
            ".architecture.yaml": _yaml(),
            "src/application/Pay.ts": 'import { Order } from "../domain/Order";\n',
            "src/domain/Invoice.ts": 'import { Pay } from "../application/Pay";\n',
        },
    )
    git_repo.commit("declare layers + new violation")

    report = analyze_changes(ChangeAnalysisRequest(path=git_repo.root, base="main"))
    assert [f.location.file for f in _layer_findings(report)] == ["src/domain/Invoice.ts"]
