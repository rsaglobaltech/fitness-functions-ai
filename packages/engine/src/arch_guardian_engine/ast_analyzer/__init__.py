"""Tree-sitter backed AST analyzer.

Public surface:
    - `analyze_repo(root)` → `RepoAnalysis` (per-file modules, imports, classes,
      functions, plus a global import DiGraph).
    - `Language`, `Module`, `ClassInfo`, `FunctionInfo`, `Import`.
"""

from arch_guardian_engine.ast_analyzer.analyzer import (
    ClassInfo,
    FunctionInfo,
    Import,
    Language,
    Module,
    RepoAnalysis,
    analyze_file,
    analyze_repo,
    language_for_path,
)

__all__ = [
    "ClassInfo",
    "FunctionInfo",
    "Import",
    "Language",
    "Module",
    "RepoAnalysis",
    "analyze_file",
    "analyze_repo",
    "language_for_path",
]
