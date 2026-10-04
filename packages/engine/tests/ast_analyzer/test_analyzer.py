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


@pytest.mark.unit
def test_spec_node_kinds_exist_in_grammars() -> None:
    from arch_guardian_engine.ast_analyzer.analyzer import _SPECS, _parser_for

    for lang, spec in _SPECS.items():
        grammar = _parser_for(lang).language
        kinds = spec.function_types | spec.class_types | spec.import_types | spec.decision_types
        unknown = sorted(k for k in kinds if grammar.id_for_node_kind(k, True) is None)
        assert unknown == [], f"{lang}: {unknown}"


@pytest.mark.unit
def test_nested_functions_own_their_decisions(tmp_path: Path) -> None:
    src = tmp_path / "m.ts"
    src.write_text(
        "function outer(xs: number[]) {\n"
        "  if (xs.length) {}\n"
        "  return xs.map((x) => (x > 0 ? x : -x));\n"
        "}\n"
        "for (const x of [1]) {}\n",
        encoding="utf-8",
    )
    module = analyze_file(src, root=tmp_path)
    assert module is not None
    cc = {f.name: f.cyclomatic_complexity for f in module.functions}
    assert cc == {"outer": 2, "<anonymous>": 2}


@pytest.mark.unit
def test_python_class_metrics_decorators_fields_and_comprehension_filters(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text(
        "class A:\n"
        "    x = 1\n"
        "    y: int = 2\n"
        "    @property\n"
        "    def p(self): return 1\n"
        "    def _q(self): return [i for i in range(3) if i]\n",
        encoding="utf-8",
    )
    module = analyze_file(src, root=tmp_path)
    assert module is not None
    a = module.classes[0]
    assert (a.public_methods, a.total_methods, a.fields) == (1, 2, 2)
    assert {f.name: f.cyclomatic_complexity for f in module.functions}["_q"] == 2


@pytest.mark.unit
def test_java_constructors_and_lambdas_are_functions(tmp_path: Path) -> None:
    src = tmp_path / "A.java"
    src.write_text(
        "class A {\n"
        "  A(int x) { if (x > 0) {} }\n"
        "  public void run(java.util.List<Integer> xs) {\n"
        "    xs.forEach(x -> { if (x > 1 && x < 5) {} });\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    module = analyze_file(src, root=tmp_path)
    assert module is not None
    cc = {f.name: f.cyclomatic_complexity for f in module.functions}
    assert cc == {"A": 2, "run": 1, "<lambda>": 3}
