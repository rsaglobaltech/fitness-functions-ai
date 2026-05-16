"""Tree-sitter analyzer: parse files, extract imports + classes + functions.

Why Tree-sitter (see ADR-0001 §D1):
    - One uniform API across languages → adding a language is a small change.
    - Error-tolerant parser: keeps working on broken / partial diffs.
    - Pure-Python install via published wheels — no native daemons.

Design:
    `analyze_file()` is the per-file entrypoint. It dispatches by language
    and returns a `Module`. Each language has an `_Extractor` that walks the
    Tree-sitter `Node` tree and emits `Import`, `ClassInfo`, `FunctionInfo`.

    `analyze_repo()` walks the repo, calls `analyze_file()` on every supported
    source file, and assembles the global import `DiGraph`. The graph is the
    backbone for the cycle detector (F2.3) and for fan-out computation in the
    God Object detector (F2.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import networkx as nx
from tree_sitter import Language as TSLanguage
from tree_sitter import Node, Parser, Tree

from arch_guardian_engine.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

_log = get_logger(__name__)


class Language(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    TSX = "tsx"
    JAVASCRIPT = "javascript"
    JAVA = "java"


_EXTS: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TSX,
    ".js": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
    ".java": Language.JAVA,
}


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".github",
        ".idea",
        ".vscode",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        "out",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "htmlcov",
        "coverage",
    }
)


def language_for_path(path: str | Path) -> Language | None:
    """Map a file path to a supported language, or None if unsupported."""
    return _EXTS.get(Path(path).suffix.lower())


# ---------------------------------------------------------------------------
# Tree-sitter parsers (lazy + cached)
# ---------------------------------------------------------------------------


def _build_parser(lang: Language) -> Parser:
    if lang is Language.PYTHON:
        import tree_sitter_python as ts_py

        ts_lang = TSLanguage(ts_py.language())
    elif lang in (Language.TYPESCRIPT, Language.TSX):
        import tree_sitter_typescript as ts_ts

        ts_lang = TSLanguage(
            ts_ts.language_tsx() if lang is Language.TSX else ts_ts.language_typescript()
        )
    elif lang is Language.JAVASCRIPT:
        # The TS grammar package also exposes a JS grammar in some versions;
        # fall back to TypeScript grammar which parses JS adequately for our
        # purposes (imports + classes + control flow).
        import tree_sitter_typescript as ts_ts

        ts_lang = TSLanguage(ts_ts.language_typescript())
    elif lang is Language.JAVA:
        import tree_sitter_java as ts_java

        ts_lang = TSLanguage(ts_java.language())
    else:  # pragma: no cover - exhaustive over StrEnum
        raise ValueError(f"unsupported language: {lang}")

    parser = Parser(ts_lang)
    return parser


_parser_cache: dict[Language, Parser] = {}


def _parser_for(lang: Language) -> Parser:
    if lang not in _parser_cache:
        _parser_cache[lang] = _build_parser(lang)
    return _parser_cache[lang]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Import:
    """A single import statement extracted from a module."""

    target: str
    line: int


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    start_line: int
    end_line: int
    parameters: int
    decision_points: int  # for cyclomatic complexity (F2.5)

    @property
    def loc(self) -> int:
        return max(1, self.end_line - self.start_line + 1)

    @property
    def cyclomatic_complexity(self) -> int:
        # McCabe simplified: 1 + (decision points)
        return 1 + self.decision_points


@dataclass(frozen=True)
class ClassInfo:
    name: str
    start_line: int
    end_line: int
    public_methods: int
    total_methods: int
    fields: int

    @property
    def loc(self) -> int:
        return max(1, self.end_line - self.start_line + 1)


@dataclass(frozen=True)
class Module:
    """One parsed source file."""

    path: Path
    language: Language
    module_id: str  # canonical dotted name relative to repo root
    imports: tuple[Import, ...]
    classes: tuple[ClassInfo, ...]
    functions: tuple[FunctionInfo, ...]


@dataclass
class RepoAnalysis:
    root: Path
    modules: dict[str, Module] = field(default_factory=dict)
    import_graph: nx.DiGraph[str] = field(default_factory=nx.DiGraph)
    skipped: list[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _walk(node: Node) -> Iterator[Node]:
    """Pre-order traversal over a Tree-sitter node."""
    yield node
    for child in node.children:
        yield from _walk(child)


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _module_id_for(path: Path, root: Path, language: Language) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = rel.parts
    if language is Language.PYTHON and parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else rel.name


# ---------------------------------------------------------------------------
# Extractors per language
# ---------------------------------------------------------------------------


class _Extractor(Protocol):
    def imports(self, tree: Tree, source: bytes) -> list[Import]: ...
    def classes(self, tree: Tree, source: bytes) -> list[ClassInfo]: ...
    def functions(self, tree: Tree, source: bytes) -> list[FunctionInfo]: ...


# --- Python ----------------------------------------------------------------

_PY_DECISION_KINDS: frozenset[str] = frozenset(
    {
        "if_statement",
        "elif_clause",
        "for_statement",
        "while_statement",
        "except_clause",
        "case_clause",
        "boolean_operator",
        "conditional_expression",
        "comprehension_if_clause",
    }
)


class _PythonExtractor:
    def imports(self, tree: Tree, source: bytes) -> list[Import]:
        out: list[Import] = []
        for node in _walk(tree.root_node):
            if node.type == "import_statement":
                for name in node.children_by_field_name("name"):
                    out.append(Import(target=_text(name, source), line=node.start_point[0] + 1))
                # Fallback when fields aren't filled: scan child dotted names.
                if not node.children_by_field_name("name"):
                    for child in node.named_children:
                        if child.type == "dotted_name":
                            out.append(
                                Import(
                                    target=_text(child, source),
                                    line=node.start_point[0] + 1,
                                )
                            )
            elif node.type == "import_from_statement":
                module_node = node.child_by_field_name("module_name")
                module_name = _text(module_node, source) if module_node else ""
                if module_name:
                    out.append(Import(target=module_name, line=node.start_point[0] + 1))
        return out

    def classes(self, tree: Tree, source: bytes) -> list[ClassInfo]:
        out: list[ClassInfo] = []
        for node in _walk(tree.root_node):
            if node.type != "class_definition":
                continue
            name_node = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if name_node is None:
                continue
            public_methods, total_methods, fields = 0, 0, 0
            if body is not None:
                for child in body.named_children:
                    if child.type == "function_definition":
                        total_methods += 1
                        n = child.child_by_field_name("name")
                        if n and not _text(n, source).startswith("_"):
                            public_methods += 1
                    elif child.type == "assignment":
                        fields += 1
            out.append(
                ClassInfo(
                    name=_text(name_node, source),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    public_methods=public_methods,
                    total_methods=total_methods,
                    fields=fields,
                )
            )
        return out

    def functions(self, tree: Tree, source: bytes) -> list[FunctionInfo]:
        out: list[FunctionInfo] = []
        for node in _walk(tree.root_node):
            if node.type != "function_definition":
                continue
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            if name_node is None:
                continue
            params = (
                sum(1 for c in params_node.named_children if c.type != "comment")
                if params_node is not None
                else 0
            )
            decisions = sum(1 for n in _walk(node) if n.type in _PY_DECISION_KINDS)
            out.append(
                FunctionInfo(
                    name=_text(name_node, source),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parameters=params,
                    decision_points=decisions,
                )
            )
        return out


# --- TypeScript / JavaScript ----------------------------------------------

_TS_DECISION_KINDS: frozenset[str] = frozenset(
    {
        "if_statement",
        "for_statement",
        "for_in_statement",
        "for_of_statement",
        "while_statement",
        "do_statement",
        "switch_case",
        "ternary_expression",
        "catch_clause",
    }
)
# `||`, `&&`, `??` are nested under `binary_expression`; counted separately.


def _count_ts_decisions(node: Node, source: bytes) -> int:
    count = 0
    for n in _walk(node):
        if n.type in _TS_DECISION_KINDS:
            count += 1
            continue
        if n.type == "binary_expression":
            op_node = n.child_by_field_name("operator")
            if op_node is not None and _text(op_node, source) in ("&&", "||", "??"):
                count += 1
    return count


class _TypeScriptExtractor:
    def imports(self, tree: Tree, source: bytes) -> list[Import]:
        out: list[Import] = []
        for node in _walk(tree.root_node):
            if node.type == "import_statement":
                src_node = node.child_by_field_name("source")
                if src_node is not None:
                    raw = _text(src_node, source).strip("\"'`")
                    out.append(Import(target=raw, line=node.start_point[0] + 1))
        return out

    def classes(self, tree: Tree, source: bytes) -> list[ClassInfo]:
        out: list[ClassInfo] = []
        for node in _walk(tree.root_node):
            if node.type != "class_declaration":
                continue
            name_node = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if name_node is None:
                continue
            public_methods, total_methods, fields = 0, 0, 0
            if body is not None:
                for child in body.named_children:
                    if child.type in ("method_definition", "abstract_method_signature"):
                        total_methods += 1
                        accessors = [
                            _text(c, source)
                            for c in child.children
                            if c.type == "accessibility_modifier"
                        ]
                        if "private" not in accessors and "protected" not in accessors:
                            public_methods += 1
                    elif child.type in ("public_field_definition", "field_definition"):
                        fields += 1
            out.append(
                ClassInfo(
                    name=_text(name_node, source),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    public_methods=public_methods,
                    total_methods=total_methods,
                    fields=fields,
                )
            )
        return out

    def functions(self, tree: Tree, source: bytes) -> list[FunctionInfo]:
        out: list[FunctionInfo] = []
        targets = {
            "function_declaration",
            "method_definition",
            "arrow_function",
            "function_expression",
        }
        for node in _walk(tree.root_node):
            if node.type not in targets:
                continue
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            params = (
                sum(1 for c in params_node.named_children if c.type != "comment")
                if params_node is not None
                else 0
            )
            name = _text(name_node, source) if name_node else "<anonymous>"
            out.append(
                FunctionInfo(
                    name=name,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parameters=params,
                    decision_points=_count_ts_decisions(node, source),
                )
            )
        return out


# --- Java ------------------------------------------------------------------

_JAVA_DECISION_KINDS: frozenset[str] = frozenset(
    {
        "if_statement",
        "for_statement",
        "enhanced_for_statement",
        "while_statement",
        "do_statement",
        "switch_label",
        "ternary_expression",
        "catch_clause",
    }
)


def _count_java_decisions(node: Node, source: bytes) -> int:
    count = 0
    for n in _walk(node):
        if n.type in _JAVA_DECISION_KINDS:
            count += 1
            continue
        if n.type == "binary_expression":
            op_node = n.child_by_field_name("operator")
            if op_node is not None and _text(op_node, source) in ("&&", "||"):
                count += 1
    return count


class _JavaExtractor:
    def imports(self, tree: Tree, source: bytes) -> list[Import]:
        out: list[Import] = []
        for node in _walk(tree.root_node):
            if node.type == "import_declaration":
                for child in node.named_children:
                    if child.type in ("scoped_identifier", "identifier"):
                        out.append(
                            Import(target=_text(child, source), line=node.start_point[0] + 1)
                        )
                        break
        return out

    def classes(self, tree: Tree, source: bytes) -> list[ClassInfo]:
        out: list[ClassInfo] = []
        for node in _walk(tree.root_node):
            if node.type not in ("class_declaration", "interface_declaration"):
                continue
            name_node = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if name_node is None:
                continue
            public_methods, total_methods, fields = 0, 0, 0
            if body is not None:
                for child in body.named_children:
                    if child.type == "method_declaration":
                        total_methods += 1
                        modifiers = next(
                            (c for c in child.children if c.type == "modifiers"),
                            None,
                        )
                        is_public = modifiers is not None and "public" in _text(modifiers, source)
                        if is_public:
                            public_methods += 1
                    elif child.type == "field_declaration":
                        fields += 1
            out.append(
                ClassInfo(
                    name=_text(name_node, source),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    public_methods=public_methods,
                    total_methods=total_methods,
                    fields=fields,
                )
            )
        return out

    def functions(self, tree: Tree, source: bytes) -> list[FunctionInfo]:
        out: list[FunctionInfo] = []
        for node in _walk(tree.root_node):
            if node.type != "method_declaration":
                continue
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            params = (
                sum(1 for c in params_node.named_children if c.type != "comment")
                if params_node is not None
                else 0
            )
            name = _text(name_node, source) if name_node else "<anonymous>"
            out.append(
                FunctionInfo(
                    name=name,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parameters=params,
                    decision_points=_count_java_decisions(node, source),
                )
            )
        return out


_EXTRACTORS: dict[Language, _Extractor] = {
    Language.PYTHON: _PythonExtractor(),
    Language.TYPESCRIPT: _TypeScriptExtractor(),
    Language.TSX: _TypeScriptExtractor(),
    Language.JAVASCRIPT: _TypeScriptExtractor(),
    Language.JAVA: _JavaExtractor(),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_file(path: str | Path, *, root: str | Path | None = None) -> Module | None:
    """Parse a single source file and return its `Module`, or None if unsupported."""
    p = Path(path).resolve()
    lang = language_for_path(p)
    if lang is None:
        return None
    parser = _parser_for(lang)
    source = p.read_bytes()
    tree = parser.parse(source)
    extractor = _EXTRACTORS[lang]
    repo_root = Path(root).resolve() if root else p.parent
    return Module(
        path=p,
        language=lang,
        module_id=_module_id_for(p, repo_root, lang),
        imports=tuple(extractor.imports(tree, source)),
        classes=tuple(extractor.classes(tree, source)),
        functions=tuple(extractor.functions(tree, source)),
    )


def _iter_source_files(root: Path) -> Iterator[Path]:
    for p in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in _EXTS:
            yield p


def analyze_repo(root: str | Path) -> RepoAnalysis:
    """Walk a repository and produce per-file modules + the global import graph."""
    repo_root = Path(root).resolve()
    if not repo_root.is_dir():
        raise FileNotFoundError(f"not a directory: {repo_root}")

    analysis = RepoAnalysis(root=repo_root)

    for path in _iter_source_files(repo_root):
        try:
            module = analyze_file(path, root=repo_root)
        except Exception as exc:
            _log.warning("ast_parse_failed", file=str(path), error=repr(exc))
            analysis.skipped.append(path)
            continue
        if module is None:
            continue
        analysis.modules[module.module_id] = module
        analysis.import_graph.add_node(module.module_id, path=str(path))

    # Build edges only after all nodes exist, so we can prefix-match imports
    # against known modules. We treat an import as "internal" if any module
    # id is a prefix or suffix of the import target's dotted form.
    known_ids = set(analysis.modules.keys())
    for module in analysis.modules.values():
        for imp in module.imports:
            target = _resolve_internal_target(imp.target, known_ids)
            if target is None or target == module.module_id:
                continue
            analysis.import_graph.add_edge(module.module_id, target)

    _log.info(
        "repo_analyzed",
        root=str(repo_root),
        modules=len(analysis.modules),
        edges=analysis.import_graph.number_of_edges(),
        skipped=len(analysis.skipped),
    )
    return analysis


_IMPORT_SUFFIXES = (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".py")


def _strip_known_suffix(value: str) -> str:
    for suffix in _IMPORT_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _resolve_internal_target(raw: str, known_ids: set[str]) -> str | None:
    """Best-effort match of an import string to a known module id.

    Strategy:
        1. Direct hit.
        2. Strip common file-extensions / relative prefixes.
        3. Prefix / suffix match against the known set (longest wins).

    Note: we use `_strip_known_suffix` instead of `str.rstrip` because rstrip
    is *set*-based — it would chew off trailing letters like 's' or 't' from
    a dotted module name, which silently mis-resolves imports.
    """
    if not raw:
        return None
    candidate = _strip_known_suffix(raw.replace("/", ".").lstrip("."))
    if candidate in known_ids:
        return candidate
    matches = [k for k in known_ids if k == candidate or k.endswith("." + candidate)]
    if matches:
        return max(matches, key=len)
    matches = [k for k in known_ids if candidate.endswith(k) or candidate.startswith(k + ".")]
    if matches:
        return max(matches, key=len)
    return None
