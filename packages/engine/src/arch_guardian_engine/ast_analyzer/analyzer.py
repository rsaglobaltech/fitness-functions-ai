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

import os
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
    """Pre-order traversal over a Tree-sitter node.

    Iterative on purpose: generated / deeply nested code would blow the
    recursion limit with a recursive generator.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


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
                if not module_name:
                    continue
                line = node.start_point[0] + 1
                names = [
                    _text(n.child_by_field_name("name") or n, source)
                    if n.type == "aliased_import"
                    else _text(n, source)
                    for n in node.children_by_field_name("name")
                ]
                if not names:  # `from x import *`
                    out.append(Import(target=module_name, line=line))
                sep = "" if module_name.endswith(".") else "."
                for imported in names:
                    # `from pkg import mod` may name a submodule or a symbol;
                    # the resolver trims trailing parts until a module matches.
                    out.append(Import(target=f"{module_name}{sep}{imported}", line=line))
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
            if node.type in ("import_statement", "export_statement"):
                src_node = node.child_by_field_name("source")
                if src_node is not None:
                    raw = _text(src_node, source).strip("\"'`")
                    out.append(Import(target=raw, line=node.start_point[0] + 1))
            elif node.type == "call_expression":
                # `require("x")` and dynamic `import("x")` with a literal specifier.
                fn = node.child_by_field_name("function")
                args = node.child_by_field_name("arguments")
                if fn is None or args is None or fn.type not in ("identifier", "import"):
                    continue
                if fn.type == "identifier" and _text(fn, source) != "require":
                    continue
                literal = next((a for a in args.named_children if a.type == "string"), None)
                if literal is not None:
                    raw = _text(literal, source).strip("\"'`")
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


DEFAULT_MAX_FILE_BYTES = 1_000_000  # bigger files are generated / vendored in practice
_SKIP_SUFFIXES = (".min.js", ".bundle.js", ".d.ts")


def _iter_source_files(root: Path, max_file_bytes: int) -> Iterator[Path]:
    """Yield supported source files, pruning skip-dirs instead of descending them."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix.lower() not in _EXTS or name.lower().endswith(_SKIP_SUFFIXES):
                continue
            if p.is_symlink():
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > max_file_bytes:
                _log.info("file_skipped_too_large", file=str(p), bytes=size)
                continue
            yield p


def analyze_repo(
    root: str | Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> RepoAnalysis:
    """Walk a repository and produce per-file modules + the global import graph."""
    repo_root = Path(root).resolve()
    if not repo_root.is_dir():
        raise FileNotFoundError(f"not a directory: {repo_root}")

    analysis = RepoAnalysis(root=repo_root)

    for path in _iter_source_files(repo_root, max_file_bytes):
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

    # Edges are built once every node exists so imports can be resolved
    # against the full module set.
    resolver = _ImportResolver(repo_root, analysis.modules)
    for module in analysis.modules.values():
        for imp in module.imports:
            target = resolver.resolve(module, imp.target)
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


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------

_IMPORT_SUFFIXES = (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".py")
_TS_ALIAS_PREFIXES = ("@/", "~/", "#/")


def _strip_known_suffix(value: str) -> str:
    # Not `str.rstrip`: that is set-based and would eat trailing 's'/'t'.
    for suffix in _IMPORT_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _common_prefix_len(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


class _ImportResolver:
    """Map raw import strings to known module ids.

    Strategy, most to least precise:
        1. Relative imports (`./x`, `../x`, Python leading dots) are resolved
           against the importing file — never by name guessing.
        2. Absolute imports: exact module id, else a dotted-suffix index lookup
           (`billing.pricing` ↔ `src.billing.pricing`), trimming trailing
           parts so `pkg.mod.Symbol` lands on `pkg.mod`.
        3. Several suffix candidates: pick the one sharing the longest prefix
           with the importer; if still tied, give up. A missing edge costs a
           missed finding; a wrong edge creates a false *critical* cycle.
    """

    def __init__(self, root: Path, modules: dict[str, Module]) -> None:
        self._root = root
        self._ids = set(modules)
        # Python absolute imports start at a sys.path root, which is never
        # inside a package; used to reject `import logging` → `pkg/logging.py`.
        self._py_packages = {m.module_id for m in modules.values() if m.path.name == "__init__.py"}
        self._suffix_index: dict[str, list[str]] = {}
        for module_id in modules:
            parts = module_id.split(".")
            for i in range(len(parts)):
                self._suffix_index.setdefault(".".join(parts[i:]), []).append(module_id)

    def resolve(self, importer: Module, raw: str) -> str | None:
        raw = raw.strip()
        if not raw:
            return None
        if importer.language is Language.PYTHON:
            if raw.startswith("."):
                return self._resolve_python_relative(importer, raw)
            return self._lookup(importer, raw.split("."), python_absolute=True)
        if importer.language is Language.JAVA:
            return self._lookup(importer, raw.split("."))
        return self._resolve_js(importer, raw)

    # -- Python --------------------------------------------------------------

    def _resolve_python_relative(self, importer: Module, raw: str) -> str | None:
        level = len(raw) - len(raw.lstrip("."))
        rest = [p for p in raw[level:].split(".") if p]
        package = importer.module_id.split(".")
        if importer.path.name != "__init__.py":
            package = package[:-1]
        if level - 1 > len(package):
            return None
        base = package[: len(package) - (level - 1)]
        parts = base + rest
        # Trim trailing parts (imported symbols) but never above the base package.
        for end in range(len(parts), len(base) - 1, -1):
            candidate = ".".join(parts[:end])
            if candidate in self._ids:
                return candidate
        return None

    # -- JS / TS -------------------------------------------------------------

    def _resolve_js(self, importer: Module, raw: str) -> str | None:
        if raw.startswith(("./", "../")) or raw in (".", ".."):
            target = os.path.normpath(importer.path.parent / raw)
            try:
                rel = Path(target).relative_to(self._root)
            except ValueError:
                return None  # escapes the repo
            dotted = _strip_known_suffix(rel.as_posix()).replace("/", ".")
            for candidate in (dotted, f"{dotted}.index"):
                if candidate in self._ids:
                    return candidate
            return None
        for prefix in _TS_ALIAS_PREFIXES:
            if raw.startswith(prefix):
                raw = raw[len(prefix) :]
                break
        else:
            if raw.startswith("@") or "/" not in raw:
                # Scoped npm package or bare package name: external.
                return None
        parts = _strip_known_suffix(raw).split("/")
        # Paths name files, not symbols: no trimming.
        return self._lookup(importer, [*parts, "index"], trim=False) or self._lookup(
            importer, parts, trim=False
        )

    # -- shared --------------------------------------------------------------

    def _lookup(
        self,
        importer: Module,
        parts: list[str],
        *,
        trim: bool = True,
        python_absolute: bool = False,
    ) -> str | None:
        parts = [p for p in parts if p]
        shortest = 1 if trim else len(parts)
        for end in range(len(parts), max(shortest, 1) - 1, -1):
            key = ".".join(parts[:end])
            if key in self._ids:
                return key
            candidates = self._suffix_index.get(key, [])
            if python_absolute:
                candidates = [c for c in candidates if self._anchored_at_root(c, end)]
            if candidates:
                return self._pick(importer, candidates)
        return None

    def _anchored_at_root(self, candidate: str, key_len: int) -> bool:
        prefix_parts = candidate.split(".")[:-key_len]
        return not prefix_parts or ".".join(prefix_parts) not in self._py_packages

    @staticmethod
    def _pick(importer: Module, candidates: list[str]) -> str | None:
        if len(candidates) == 1:
            return candidates[0]
        own = tuple(importer.module_id.split("."))
        scored = sorted(
            ((_common_prefix_len(own, tuple(c.split("."))), c) for c in candidates),
            reverse=True,
        )
        if scored[0][0] == scored[1][0]:
            return None
        return scored[0][1]
