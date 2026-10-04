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
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import networkx as nx
from tree_sitter import Language as TSLanguage
from tree_sitter import Node, Parser, Tree

from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.paths import matches_any, matches_glob

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
    """Parsed modules plus their dependencies.

    `import_graph` edges carry a `lines` attribute: the source lines (in the
    importing module) of every import producing that edge. Imports that do not
    resolve to a repo module are kept in `external_imports` (third-party or
    stdlib), which layer rules use to forbid e.g. ORMs inside the domain.
    """

    root: Path
    modules: dict[str, Module] = field(default_factory=dict)
    import_graph: nx.DiGraph[str] = field(default_factory=nx.DiGraph)
    external_imports: dict[str, list[Import]] = field(default_factory=dict)
    skipped: list[Path] = field(default_factory=list)

    def rel_path(self, module_id: str) -> str:
        """POSIX path of a module relative to the repo root."""
        return self.modules[module_id].path.relative_to(self.root).as_posix()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
#
# Each file is scanned in ONE pre-order pass over named nodes (`_scan`). Every
# node is tagged with its innermost enclosing function, so a decision point
# counts toward exactly one function: a callback's branches belong to the
# callback, not to the function that defines it (same model as ESLint's
# `complexity` rule). This is also what keeps the scan linear in file size.


def _params(node: Node) -> int:
    params_node = node.child_by_field_name("parameters")
    if params_node is None:
        return 0
    return sum(1 for c in params_node.named_children if c.type != "comment")


def _line(node: Node) -> int:
    return node.start_point[0] + 1


class _LangSpec:
    """Per-language node vocabulary + hooks used by `_scan`."""

    function_types: frozenset[str]
    class_types: frozenset[str]
    import_types: frozenset[str]
    decision_types: frozenset[str]
    logical_ops: frozenset[str] = frozenset()  # operators of `binary_expression` that branch

    def imports_of(self, node: Node, source: bytes) -> list[Import]:
        raise NotImplementedError

    def class_of(self, node: Node, source: bytes) -> ClassInfo | None:
        raise NotImplementedError

    def function_name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        return _text(name_node, source) if name_node else "<anonymous>"


def _class_info(node: Node, source: bytes, counts: tuple[int, int, int]) -> ClassInfo | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    public_methods, total_methods, fields = counts
    return ClassInfo(
        name=_text(name_node, source),
        start_line=_line(node),
        end_line=node.end_point[0] + 1,
        public_methods=public_methods,
        total_methods=total_methods,
        fields=fields,
    )


def _scan(
    tree: Tree, source: bytes, spec: _LangSpec
) -> tuple[list[Import], list[ClassInfo], list[FunctionInfo]]:
    imports: list[Import] = []
    classes: list[ClassInfo] = []
    fn_nodes: list[Node] = []
    decisions: list[int] = []

    stack: list[tuple[Node, int]] = [(tree.root_node, -1)]
    while stack:
        node, ctx = stack.pop()
        kind = node.type
        if ctx >= 0:
            if kind in spec.decision_types:
                decisions[ctx] += 1
            elif kind == "binary_expression" and spec.logical_ops:
                op = node.child_by_field_name("operator")
                if op is not None and _text(op, source) in spec.logical_ops:
                    decisions[ctx] += 1
        if kind in spec.function_types:
            fn_nodes.append(node)
            decisions.append(0)
            ctx = len(fn_nodes) - 1
        elif kind in spec.class_types:
            info = spec.class_of(node, source)
            if info is not None:
                classes.append(info)
        if kind in spec.import_types:
            imports.extend(spec.imports_of(node, source))
        children = node.named_children
        if children:
            stack.extend((child, ctx) for child in reversed(children))

    functions: list[FunctionInfo] = []
    for fn, count in zip(fn_nodes, decisions, strict=True):
        name = spec.function_name(fn, source)
        if name is None:
            continue
        functions.append(
            FunctionInfo(
                name=name,
                start_line=_line(fn),
                end_line=fn.end_point[0] + 1,
                parameters=_params(fn),
                decision_points=count,
            )
        )
    return imports, classes, functions


# --- Python ----------------------------------------------------------------


class _PythonSpec(_LangSpec):
    function_types = frozenset({"function_definition"})
    class_types = frozenset({"class_definition"})
    import_types = frozenset({"import_statement", "import_from_statement"})
    decision_types = frozenset(
        {
            "if_statement",
            "elif_clause",
            "for_statement",
            "while_statement",
            "except_clause",
            "case_clause",
            "boolean_operator",
            "conditional_expression",
            "if_clause",  # comprehension filter
        }
    )

    def imports_of(self, node: Node, source: bytes) -> list[Import]:
        line = _line(node)
        if node.type == "import_statement":
            names = node.children_by_field_name("name") or [
                c for c in node.named_children if c.type == "dotted_name"
            ]
            return [
                Import(
                    target=_text(n.child_by_field_name("name") or n, source)
                    if n.type == "aliased_import"
                    else _text(n, source),
                    line=line,
                )
                for n in names
            ]
        module_node = node.child_by_field_name("module_name")
        module_name = _text(module_node, source) if module_node else ""
        if not module_name:
            return []
        imported = [
            _text(n.child_by_field_name("name") or n, source)
            if n.type == "aliased_import"
            else _text(n, source)
            for n in node.children_by_field_name("name")
        ]
        if not imported:  # `from x import *`
            return [Import(target=module_name, line=line)]
        sep = "" if module_name.endswith(".") else "."
        # `from pkg import mod` may name a submodule or a symbol; the resolver
        # trims trailing parts until a module matches.
        return [Import(target=f"{module_name}{sep}{name}", line=line) for name in imported]

    def class_of(self, node: Node, source: bytes) -> ClassInfo | None:
        public_methods = total_methods = fields = 0
        body = node.child_by_field_name("body")
        for child in body.named_children if body is not None else ():
            if child.type == "decorated_definition":
                child = child.child_by_field_name("definition") or child
            if child.type == "function_definition":
                total_methods += 1
                n = child.child_by_field_name("name")
                if n and not _text(n, source).startswith("_"):
                    public_methods += 1
            elif child.type == "expression_statement" and any(
                c.type == "assignment" for c in child.named_children
            ):
                fields += 1
        return _class_info(node, source, (public_methods, total_methods, fields))

    def function_name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        return _text(name_node, source) if name_node else None


# --- TypeScript / JavaScript ----------------------------------------------


class _TypeScriptSpec(_LangSpec):
    function_types = frozenset(
        {
            "function_declaration",
            "generator_function_declaration",
            "method_definition",
            "arrow_function",
            "function_expression",
        }
    )
    class_types = frozenset({"class_declaration", "abstract_class_declaration", "class"})
    import_types = frozenset({"import_statement", "export_statement", "call_expression"})
    decision_types = frozenset(
        {
            "if_statement",
            "for_statement",
            "for_in_statement",  # also covers for...of in this grammar
            "while_statement",
            "do_statement",
            "switch_case",
            "ternary_expression",
            "catch_clause",
        }
    )
    logical_ops = frozenset({"&&", "||", "??"})

    def imports_of(self, node: Node, source: bytes) -> list[Import]:
        if node.type != "call_expression":
            src_node = node.child_by_field_name("source")
            if src_node is None:
                return []
            return [Import(target=_text(src_node, source).strip("\"'`"), line=_line(node))]
        # `require("x")` and dynamic `import("x")` with a literal specifier.
        fn = node.child_by_field_name("function")
        if fn is None or fn.type not in ("identifier", "import"):
            return []
        if fn.type == "identifier" and _text(fn, source) != "require":
            return []
        args = node.child_by_field_name("arguments")
        literal = (
            next((a for a in args.named_children if a.type == "string"), None)
            if args is not None
            else None
        )
        if literal is None:
            return []
        return [Import(target=_text(literal, source).strip("\"'`"), line=_line(node))]

    def class_of(self, node: Node, source: bytes) -> ClassInfo | None:
        public_methods = total_methods = fields = 0
        body = node.child_by_field_name("body")
        for child in body.named_children if body is not None else ():
            if child.type in ("method_definition", "abstract_method_signature"):
                total_methods += 1
                accessors = {
                    _text(c, source) for c in child.children if c.type == "accessibility_modifier"
                }
                name = child.child_by_field_name("name")
                is_private_name = name is not None and name.type == "private_property_identifier"
                if not accessors & {"private", "protected"} and not is_private_name:
                    public_methods += 1
            elif child.type in ("public_field_definition", "field_definition"):
                fields += 1
        return _class_info(node, source, (public_methods, total_methods, fields))


# --- Java ------------------------------------------------------------------


class _JavaSpec(_LangSpec):
    function_types = frozenset(
        {"method_declaration", "constructor_declaration", "lambda_expression"}
    )
    class_types = frozenset(
        {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
    )
    import_types = frozenset({"import_declaration"})
    decision_types = frozenset(
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
    logical_ops = frozenset({"&&", "||"})

    def imports_of(self, node: Node, source: bytes) -> list[Import]:
        for child in node.named_children:
            if child.type in ("scoped_identifier", "identifier"):
                return [Import(target=_text(child, source), line=_line(node))]
        return []

    def class_of(self, node: Node, source: bytes) -> ClassInfo | None:
        public_methods = total_methods = fields = 0
        body = node.child_by_field_name("body")
        members = body.named_children if body is not None else []
        if node.type == "enum_declaration" and body is not None:
            decls = next((c for c in members if c.type == "enum_body_declarations"), None)
            members = decls.named_children if decls is not None else []
        for child in members:
            if child.type == "method_declaration":
                total_methods += 1
                modifiers = next((c for c in child.children if c.type == "modifiers"), None)
                if modifiers is not None and "public" in _text(modifiers, source).split():
                    public_methods += 1
            elif child.type == "field_declaration":
                fields += 1
        return _class_info(node, source, (public_methods, total_methods, fields))

    def function_name(self, node: Node, source: bytes) -> str | None:
        if node.type == "lambda_expression":
            return "<lambda>"
        return super().function_name(node, source)


_SPECS: dict[Language, _LangSpec] = {
    Language.PYTHON: _PythonSpec(),
    Language.TYPESCRIPT: _TypeScriptSpec(),
    Language.TSX: _TypeScriptSpec(),
    Language.JAVASCRIPT: _TypeScriptSpec(),
    Language.JAVA: _JavaSpec(),
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
    imports, classes, functions = _scan(tree, source, _SPECS[lang])
    repo_root = Path(root).resolve() if root else p.parent
    return Module(
        path=p,
        language=lang,
        module_id=_module_id_for(p, repo_root, lang),
        imports=tuple(imports),
        classes=tuple(classes),
        functions=tuple(functions),
    )


DEFAULT_MAX_FILE_BYTES = 1_000_000  # bigger files are generated / vendored in practice
_SKIP_SUFFIXES = (".min.js", ".bundle.js", ".d.ts")


def _iter_source_files(root: Path, max_file_bytes: int, exclude: tuple[str, ...]) -> Iterator[Path]:
    """Yield supported source files, pruning skip-dirs instead of descending them."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _SKIP_DIRS and not _dir_excluded((rel_dir / d).as_posix(), exclude)
        )
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix.lower() not in _EXTS or name.lower().endswith(_SKIP_SUFFIXES):
                continue
            if exclude and matches_any((rel_dir / name).as_posix(), exclude):
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


_PARALLEL_MIN_FILES = 64  # below this, process start-up costs more than it saves
_MAX_AUTO_JOBS = 8

_ParseResult = tuple[Path, "Module | None", "str | None"]


def _parse_one(path: Path, root: Path) -> _ParseResult:
    try:
        return path, analyze_file(path, root=root), None
    except Exception as exc:  # one broken file must not abort the analysis
        return path, None, repr(exc)


def _parse_chunk(paths: list[Path], root: Path) -> list[_ParseResult]:
    return [_parse_one(p, root) for p in paths]


def _parse_all(paths: list[Path], root: Path, jobs: int) -> list[_ParseResult]:
    workers = jobs if jobs > 0 else min(os.cpu_count() or 1, _MAX_AUTO_JOBS)
    if workers <= 1 or len(paths) < _PARALLEL_MIN_FILES:
        return _parse_chunk(paths, root)
    # Contiguous chunks keep result order deterministic and amortise IPC.
    size = max(16, len(paths) // (workers * 4))
    chunks = [paths[i : i + size] for i in range(0, len(paths), size)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = pool.map(_parse_chunk, chunks, [root] * len(chunks))
        return [r for chunk in results for r in chunk]


def _dir_excluded(rel_dir: str, exclude: tuple[str, ...]) -> bool:
    # `fixtures/**` must prune the `fixtures` dir itself, not only its files.
    return any(
        matches_glob(rel_dir, p) or (p.endswith("/**") and matches_glob(rel_dir, p[:-3]))
        for p in exclude
    )


def analyze_repo(
    root: str | Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    exclude: tuple[str, ...] = (),
    jobs: int = 0,
) -> RepoAnalysis:
    """Walk a repository and produce per-file modules + the global import graph.

    `exclude` holds repo-relative globs (see `arch_guardian_engine.paths`).
    `jobs` is the number of parser processes; 0 picks one per CPU (capped).
    """
    repo_root = Path(root).resolve()
    if not repo_root.is_dir():
        raise FileNotFoundError(f"not a directory: {repo_root}")

    analysis = RepoAnalysis(root=repo_root)
    paths = list(_iter_source_files(repo_root, max_file_bytes, exclude))

    for path, module, error in _parse_all(paths, repo_root, jobs):
        if error is not None:
            _log.warning("ast_parse_failed", file=str(path), error=error)
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
            if target is None:
                analysis.external_imports.setdefault(module.module_id, []).append(imp)
                continue
            if target == module.module_id:
                continue
            graph = analysis.import_graph
            if graph.has_edge(module.module_id, target):
                graph.edges[module.module_id, target]["lines"].append(imp.line)
            else:
                graph.add_edge(module.module_id, target, lines=[imp.line])

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
