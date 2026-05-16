"""Heuristic detector for architectural style.

The detector walks a repository and assigns a score per candidate style based
on three independent signal sources:

    1. Folder names (strong signal — explicit layout intent).
    2. Manifest files (medium signal — e.g. spring-modulith in pom.xml).
    3. Filename keywords (weak signal — supports the verdict but never decides
       on its own).

Each signal contributes weighted "hits". The style with the highest score wins,
its confidence is its share of the total scored points (in [0, 1]), and the
detector reports the matched evidence so the resolver / logs can explain *why*
a verdict was chosen.

This module is intentionally pure-Python with no heavy dependencies — fast
enough to run unconditionally on every analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from arch_guardian_engine.config.loader import Style
from arch_guardian_engine.logging import get_logger

_log = get_logger(__name__)

# Directories that are noise — we never descend into them.
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


@dataclass(frozen=True)
class StyleConfidence:
    """A single candidate style with its weighted score and evidence."""

    style: Style
    score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class DetectionResult:
    """Output of the detector: best guess + all scored candidates."""

    style: Style
    confidence: float
    evidence: tuple[str, ...]
    candidates: tuple[StyleConfidence, ...]

    @property
    def is_confident(self) -> bool:
        """Confidence threshold used by the resolver (see plan F1.4)."""
        return self.confidence >= 0.8 and self.style != Style.UNIVERSAL


# Weights per signal source. Folder hits dominate because they are the
# clearest indicator of layout intent; manifests confirm; filename keywords
# only nudge the score.
_W_FOLDER = 3.0
_W_MANIFEST = 2.0
_W_FILENAME = 1.0


# Folder fragments that imply each style. Substrings are matched against the
# normalized path (forward slashes, lower case), so 'src/domain/ports' will
# match 'domain' for Hexagonal and 'ports' for Hexagonal as well.
_FOLDER_SIGNALS: dict[Style, tuple[str, ...]] = {
    Style.HEXAGONAL: (
        "/domain/",
        "/application/",
        "/infrastructure/",
        "/adapters/",
        "/ports/",
        "/use_cases/",
        "/use-cases/",
        "/usecases/",
    ),
    Style.MVC: (
        "/controllers/",
        "/views/",
        "/models/",
        "/templates/",
        "app/controllers",
        "app/views",
        "app/models",
    ),
    Style.MICROSERVICES: (
        "/services/",
        "services/",
    ),
    Style.MODULAR_MONOLITH: (
        "/modules/",
        "modules/",
    ),
    Style.FEATURE_SLICED_DESIGN: (
        "src/shared/",
        "src/entities/",
        "src/features/",
        "src/widgets/",
        "src/pages/",
        "src/app/",
    ),
    Style.VERTICAL_SLICE: (
        "src/features/",
        "/features/",
        "/shared/",
    ),
    Style.EVENT_DRIVEN_CQRS: (
        "/commands/",
        "/queries/",
        "/events/",
        "/handlers/",
    ),
}


# Filename keywords that hint at a style.
_FILENAME_SIGNALS: dict[Style, tuple[str, ...]] = {
    Style.HEXAGONAL: ("repository", "port", "adapter", "usecase"),
    Style.MVC: ("controller", "view", "model"),
    Style.MICROSERVICES: ("service", "client", "consumer", "producer"),
    Style.EVENT_DRIVEN_CQRS: ("command", "query", "event", "handler", "saga"),
    Style.FEATURE_SLICED_DESIGN: ("widget", "slice"),
}


# Manifest files whose *contents* hint at a style (substring match).
_MANIFEST_SIGNALS: tuple[tuple[Style, str, tuple[str, ...]], ...] = (
    (Style.MODULAR_MONOLITH, "pom.xml", ("spring-modulith",)),
    (Style.MODULAR_MONOLITH, "build.gradle", ("spring-modulith",)),
    (Style.MODULAR_MONOLITH, "build.gradle.kts", ("spring-modulith",)),
    (Style.MICROSERVICES, "docker-compose.yml", ("services:",)),
    (Style.MICROSERVICES, "docker-compose.yaml", ("services:",)),
    (Style.MICROSERVICES, "skaffold.yaml", ("kind: Config",)),
    (Style.MVC, "Gemfile", ("rails",)),
    (Style.MVC, "manage.py", ("django",)),
)


@dataclass
class _Scoreboard:
    scores: dict[Style, float] = field(default_factory=dict)
    evidence: dict[Style, list[str]] = field(default_factory=dict)

    def add(self, style: Style, weight: float, evidence: str) -> None:
        self.scores[style] = self.scores.get(style, 0.0) + weight
        self.evidence.setdefault(style, []).append(evidence)


def _normalize(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix().lower()
    return f"/{rel}/"


def _walk_paths(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        # Skip noise directories early.
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def _score_folders(paths: list[Path], root: Path, board: _Scoreboard) -> None:
    seen_evidence: set[tuple[Style, str]] = set()
    for p in paths:
        if not p.is_dir():
            continue
        norm = _normalize(p, root)
        for style, signals in _FOLDER_SIGNALS.items():
            for signal in signals:
                if signal in norm and (style, signal) not in seen_evidence:
                    seen_evidence.add((style, signal))
                    board.add(style, _W_FOLDER, f"folder:{signal}")


def _score_filenames(paths: list[Path], board: _Scoreboard) -> None:
    seen_evidence: set[tuple[Style, str]] = set()
    for p in paths:
        if not p.is_file():
            continue
        stem = p.stem.lower()
        for style, keywords in _FILENAME_SIGNALS.items():
            for kw in keywords:
                if kw in stem and (style, kw) not in seen_evidence:
                    seen_evidence.add((style, kw))
                    board.add(style, _W_FILENAME, f"filename-keyword:{kw}")


def _score_manifests(root: Path, board: _Scoreboard) -> None:
    for style, manifest_name, needles in _MANIFEST_SIGNALS:
        candidate = root / manifest_name
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for needle in needles:
            if needle.lower() in content.lower():
                board.add(style, _W_MANIFEST, f"manifest:{manifest_name}:{needle}")


# When computing the winner's confidence we discount the runner-up's score
# rather than treating it as a full competitor: many styles share folder
# fragments ("/features/", "/handlers/", "service"-ish names) so a clear winner
# should not be punished for incidental overlap with a weaker candidate.
# Empirically RUNNER_UP_WEIGHT = 0.5 keeps the high-confidence path firing for
# clear layouts while keeping ambiguous repos below 0.8.
_RUNNER_UP_WEIGHT = 0.5


def _winner(board: _Scoreboard) -> DetectionResult:
    if not board.scores:
        return DetectionResult(
            style=Style.UNIVERSAL,
            confidence=0.0,
            evidence=(),
            candidates=(),
        )

    candidates = tuple(
        StyleConfidence(
            style=style,
            score=score,
            evidence=tuple(board.evidence.get(style, ())),
        )
        for style, score in sorted(board.scores.items(), key=lambda kv: kv[1], reverse=True)
    )
    winner = candidates[0]
    runner_up_score = candidates[1].score if len(candidates) > 1 else 0.0
    denom = winner.score + _RUNNER_UP_WEIGHT * runner_up_score
    confidence = winner.score / denom if denom > 0 else 0.0
    return DetectionResult(
        style=winner.style,
        confidence=confidence,
        evidence=winner.evidence,
        candidates=candidates,
    )


def detect_style(repo_root: str | Path) -> DetectionResult:
    """Inspect a repository and return the best architectural-style guess.

    Always returns a result. If no signals fire the verdict is
    `Style.UNIVERSAL` with confidence 0.0, which the resolver treats as
    "fallback to universal rules".
    """
    root = Path(repo_root).resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"repo_root does not exist: {root}")

    board = _Scoreboard()
    paths = _walk_paths(root)
    _score_folders(paths, root, board)
    _score_filenames(paths, board)
    _score_manifests(root, board)
    result = _winner(board)

    _log.info(
        "style_detection_completed",
        style=result.style.value,
        confidence=round(result.confidence, 3),
        candidates=[
            {
                "style": c.style.value,
                "score": round(c.score, 2),
                "evidence_count": len(c.evidence),
            }
            for c in result.candidates
        ],
    )
    return result
