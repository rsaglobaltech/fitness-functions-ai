"""Layer dependency rules (Hexagonal / Clean / Onion / Layered / FSD).

Layout contract, under `layout:` in `.architecture.yaml`:

    layers:
      domain:
        paths: ["src/domain/**"]
        can_depend_on: []
        forbidden_imports: ["@prisma/*", "sqlalchemy"]   # optional, external packages
      application:
        paths: ["src/application/**"]
        can_depend_on: ["domain"]

Feature-Sliced Design may instead declare `layers_order` (lowest first) plus
`paths`; each layer may then depend only on the layers below it.

Semantics:
    - A file belongs to the layer whose matching `paths` glob is the most
      specific (longest pattern); ties go to declaration order.
    - Imports inside the same layer are always allowed. Files outside every
      layer are neither checked nor protected.
    - `forbidden_imports` match *unresolved* (external) import specifiers with
      fnmatch; a bare `pkg` also covers `pkg.sub` and `pkg/sub`.
    - One finding per (importing file, imported file) pair, anchored at the
      first offending import line.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from arch_guardian_engine.ast_analyzer import RepoAnalysis
from arch_guardian_engine.config import ConfigError, Severity, Style
from arch_guardian_engine.findings import Finding, FindingLocation, FindingSource
from arch_guardian_engine.paths import matches_glob

RULE_NAME = "layer_violation"

_FIX = (
    "Depend on an abstraction owned by the inner layer (a port / interface) and "
    "let the outer layer provide the implementation through dependency injection."
)


@dataclass(frozen=True)
class LayerSpec:
    name: str
    paths: tuple[str, ...]
    can_depend_on: frozenset[str]
    forbidden_imports: tuple[str, ...] = ()


def _str_list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"layout: '{where}' must be a list of non-empty strings")
    return tuple(value)


def _from_layers(raw: Any) -> list[LayerSpec]:
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("layout: 'layers' must be a non-empty mapping of layer name → spec")
    specs: list[LayerSpec] = []
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"layout: layer '{name}' must be a mapping")
        unknown = set(spec) - {"paths", "can_depend_on", "forbidden_imports"}
        if unknown:
            raise ConfigError(f"layout: layer '{name}' has unknown keys {sorted(unknown)}")
        paths = _str_list(spec.get("paths"), f"layers.{name}.paths")
        if not paths:
            raise ConfigError(f"layout: layer '{name}' needs at least one path")
        specs.append(
            LayerSpec(
                name=str(name),
                paths=paths,
                can_depend_on=frozenset(
                    _str_list(spec.get("can_depend_on"), f"layers.{name}.can_depend_on")
                ),
                forbidden_imports=_str_list(
                    spec.get("forbidden_imports"), f"layers.{name}.forbidden_imports"
                ),
            )
        )
    names = {s.name for s in specs}
    for s in specs:
        missing = s.can_depend_on - names
        if missing:
            raise ConfigError(
                f"layout: layer '{s.name}' can_depend_on unknown layers {sorted(missing)}"
            )
    return specs


def _from_layers_order(order: Any, paths: Any) -> list[LayerSpec]:
    names = _str_list(order, "layers_order")
    if not isinstance(paths, dict):
        raise ConfigError("layout: 'layers_order' requires a 'paths' mapping")
    specs: list[LayerSpec] = []
    for i, name in enumerate(names):
        raw_paths = paths.get(name)
        layer_paths = (raw_paths,) if isinstance(raw_paths, str) else _str_list(raw_paths, name)
        if not layer_paths:
            raise ConfigError(f"layout: no paths declared for layer '{name}'")
        specs.append(LayerSpec(name, layer_paths, frozenset(names[:i])))
    return specs


def parse_layers(style: Style, layout: dict[str, Any]) -> list[LayerSpec] | None:
    """Layer specs declared in `layout`, or None when the layout has no layers."""
    if "layers" in layout:
        return _from_layers(layout["layers"])
    if style is Style.FEATURE_SLICED_DESIGN and "layers_order" in layout:
        return _from_layers_order(layout["layers_order"], layout.get("paths"))
    return None


class _LayerIndex:
    def __init__(self, layers: list[LayerSpec]) -> None:
        self._patterns = sorted(
            ((p, i, layer) for i, layer in enumerate(layers) for p in layer.paths),
            key=lambda t: (-len(t[0]), t[1]),
        )
        self._cache: dict[str, LayerSpec | None] = {}

    def layer_of(self, rel_path: str) -> LayerSpec | None:
        if rel_path not in self._cache:
            self._cache[rel_path] = next(
                (layer for p, _, layer in self._patterns if matches_glob(rel_path, p)), None
            )
        return self._cache[rel_path]


def _forbidden(spec: str, patterns: tuple[str, ...]) -> str | None:
    for p in patterns:
        if fnmatchcase(spec, p) or spec.startswith((f"{p}.", f"{p}/")):
            return p
    return None


def _allowed(layer: LayerSpec) -> str:
    return ", ".join(sorted(layer.can_depend_on)) or "none"


def detect_layer_violations(
    analysis: RepoAnalysis,
    layers: list[LayerSpec],
    *,
    style: Style,
    severity: Severity,
    rule_pack: str | None = None,
) -> list[Finding]:
    rule_id = f"{style.value}.{RULE_NAME}"
    index = _LayerIndex(layers)
    findings: list[Finding] = []

    def finding(
        file: str, line: int, symbol: str, title: str, message: str, **meta: str
    ) -> Finding:
        return Finding(
            rule_id=rule_id,
            severity=severity,
            title=title,
            message=message,
            location=FindingLocation(file=file, line=line, symbol=symbol),
            source=FindingSource.RULE_PACK,
            rule_pack=rule_pack,
            suggested_fix=_FIX,
            metadata=dict(meta),
        )

    for src, dst, data in sorted(analysis.import_graph.edges(data=True)):
        src_file, dst_file = analysis.rel_path(src), analysis.rel_path(dst)
        src_layer, dst_layer = index.layer_of(src_file), index.layer_of(dst_file)
        if src_layer is None or dst_layer is None or src_layer is dst_layer:
            continue
        if dst_layer.name in src_layer.can_depend_on:
            continue
        findings.append(
            finding(
                src_file,
                min(data.get("lines") or [1]),
                f"{dst_layer.name}:{dst_file}",
                f"Layer '{src_layer.name}' depends on '{dst_layer.name}'",
                f"{src_file} ({src_layer.name}) imports {dst_file} ({dst_layer.name}). "
                f"Layer '{src_layer.name}' may only depend on: {_allowed(src_layer)}.",
                from_layer=src_layer.name,
                to_layer=dst_layer.name,
                target_file=dst_file,
                kind="internal",
            )
        )

    for module_id, imports in sorted(analysis.external_imports.items()):
        src_file = analysis.rel_path(module_id)
        src_layer = index.layer_of(src_file)
        if src_layer is None or not src_layer.forbidden_imports:
            continue
        # `from pkg.mod import a, b` yields one import per name: report the
        # statement once per matched pattern.
        seen: set[tuple[int, str]] = set()
        for imp in sorted(imports, key=lambda i: i.line):
            pattern = _forbidden(imp.target, src_layer.forbidden_imports)
            if pattern is None or (imp.line, pattern) in seen:
                continue
            seen.add((imp.line, pattern))
            findings.append(
                finding(
                    src_file,
                    imp.line,
                    f"external:{pattern}",
                    f"Layer '{src_layer.name}' imports forbidden package '{imp.target}'",
                    f"{src_file} ({src_layer.name}) imports '{imp.target}', which matches "
                    f"forbidden pattern '{pattern}' for this layer.",
                    from_layer=src_layer.name,
                    target_package=imp.target,
                    kind="external",
                )
            )

    return findings
