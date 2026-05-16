"""Tests for the Tree-sitter AST analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.ast_analyzer import (
    Language,
    analyze_file,
    analyze_repo,
    language_for_path,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.unit
def test_language_for_path() -> None:
    assert language_for_path("a.py") is Language.PYTHON
    assert language_for_path("a.ts") is Language.TYPESCRIPT
    assert language_for_path("a.tsx") is Language.TSX
    assert language_for_path("a.java") is Language.JAVA
    assert language_for_path("a.txt") is None


@pytest.mark.unit
def test_analyze_python_file_extracts_imports_classes_functions(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text(
        '"""m."""\n'
        "from os import path\n"
        "import json\n"
        "\n"
        "class Foo:\n"
        "    def bar(self, x: int) -> int:\n"
        "        if x > 0:\n"
        "            return x\n"
        "        return -x\n"
        "\n"
        "def top(x: int) -> int:\n"
        "    return x\n",
        encoding="utf-8",
    )
    module = analyze_file(src, root=tmp_path)
    assert module is not None
    assert module.language is Language.PYTHON
    targets = {imp.target for imp in module.imports}
    assert "json" in targets
    assert any("os" in t for t in targets)
    assert [c.name for c in module.classes] == ["Foo"]
    foo = module.classes[0]
    assert foo.public_methods == 1
    assert any(f.name == "bar" for f in module.functions)
    bar = next(f for f in module.functions if f.name == "bar")
    assert bar.cyclomatic_complexity >= 2


@pytest.mark.unit
def test_analyze_typescript_file(tmp_path: Path) -> None:
    src = tmp_path / "Mod.ts"
    src.write_text(
        'import { foo } from "./foo";\n'
        "\n"
        "export class Bar {\n"
        "  public greet(name: string): string {\n"
        '    return name.length > 0 ? "hi " + name : "hi";\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    module = analyze_file(src, root=tmp_path)
    assert module is not None
    assert module.language is Language.TYPESCRIPT
    assert any("foo" in imp.target for imp in module.imports)
    assert [c.name for c in module.classes] == ["Bar"]


@pytest.mark.unit
def test_analyze_repo_builds_import_graph() -> None:
    repo = FIXTURES / "planted_violations"
    analysis = analyze_repo(repo)
    assert len(analysis.modules) > 5
    assert analysis.import_graph.number_of_edges() >= 2


@pytest.mark.unit
def test_unsupported_file_returns_none(tmp_path: Path) -> None:
    src = tmp_path / "note.txt"
    src.write_text("hello", encoding="utf-8")
    assert analyze_file(src, root=tmp_path) is None
