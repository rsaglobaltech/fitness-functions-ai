"""`guardian` command-line interface.

Exit codes (stable contract for CI):
    0  analysis ran, nothing at or above `--fail-on`
    1  analysis ran, findings at or above `--fail-on`
    2  usage / configuration / git error (e.g. invalid .architecture.yaml)
    3  unexpected internal error
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from arch_guardian_engine import __version__
from arch_guardian_engine.analyzer import ChangeAnalysisRequest, analyze_changes
from arch_guardian_engine.config import Severity
from arch_guardian_engine.diff import GitError, git_toplevel
from arch_guardian_engine.findings import AnalysisReport
from arch_guardian_engine.logging import configure_logging, get_logger
from arch_guardian_engine.report import OutputFormat, render

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3


class FailOn(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"
    NEVER = "never"


_THRESHOLD: dict[FailOn, frozenset[Severity]] = {
    FailOn.CRITICAL: frozenset({Severity.CRITICAL}),
    FailOn.WARNING: frozenset({Severity.CRITICAL, Severity.WARNING}),
    FailOn.SUGGESTION: frozenset({Severity.CRITICAL, Severity.WARNING, Severity.SUGGESTION}),
    FailOn.NEVER: frozenset(),
}

app = typer.Typer(
    name="guardian",
    help="Architectural fitness functions for your repository.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _err(message: str) -> None:
    typer.echo(f"guardian: {message}", err=True)


def _path_prefix(path: Path) -> str:
    """Path of the analysed dir relative to the git root ('' outside git)."""
    try:
        return path.relative_to(git_toplevel(path)).as_posix()
    except (GitError, ValueError):
        return ""


def _write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _parse_reports(specs: list[str]) -> list[tuple[OutputFormat, Path]]:
    parsed: list[tuple[OutputFormat, Path]] = []
    valid = ", ".join(f.value for f in OutputFormat)
    for spec in specs:
        fmt, sep, target = spec.partition(":")
        if not sep or not target:
            raise typer.BadParameter(f"expected FORMAT:PATH, got {spec!r}", param_hint="--report")
        try:
            parsed.append((OutputFormat(fmt), Path(target)))
        except ValueError as exc:
            raise typer.BadParameter(
                f"unknown format {fmt!r} (valid: {valid})", param_hint="--report"
            ) from exc
    return parsed


def exit_code_for(report: AnalysisReport, fail_on: FailOn) -> int:
    blocking = _THRESHOLD[fail_on]
    return EXIT_FINDINGS if any(f.severity in blocking for f in report.findings) else EXIT_OK


@app.command()
def analyze(
    path: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, resolve_path=True, help="Repository root."),
    ] = Path("."),
    base: Annotated[
        str | None,
        typer.Option(
            help="Report only findings new since the merge-base with this ref "
            "(e.g. origin/main). Requires full git history."
        ),
    ] = None,
    head: Annotated[
        str, typer.Option(help="Ref to analyse. 'HEAD' uses the working tree as-is.")
    ] = "HEAD",
    output_format: Annotated[
        OutputFormat, typer.Option("--format", "-f", help="Report format.")
    ] = OutputFormat.TEXT,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write report here instead of stdout."),
    ] = None,
    extra_reports: Annotated[
        list[str] | None,
        typer.Option(
            "--report",
            help="Extra report from the same run, as FORMAT:PATH (repeatable), "
            "e.g. --report sarif:guardian.sarif --report text:summary.txt",
        ),
    ] = None,
    fail_on: Annotated[
        FailOn, typer.Option(help="Lowest severity that makes the command exit 1.")
    ] = FailOn.CRITICAL,
    allow_invalid_config: Annotated[
        bool,
        typer.Option(help="Do not exit 2 when .architecture.yaml is invalid; fall back instead."),
    ] = False,
    jobs: Annotated[
        int, typer.Option(min=0, help="Parser processes (0 = one per CPU, max 8).")
    ] = 0,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log progress.")] = False,
    log_json: Annotated[bool, typer.Option(help="Emit logs as JSON (stderr).")] = False,
) -> None:
    """Analyse a repository and report architectural findings."""
    configure_logging(level="INFO" if verbose else "WARNING", json_logs=log_json)
    log = get_logger("arch_guardian_engine.cli")
    extras = _parse_reports(extra_reports or [])

    try:
        report = analyze_changes(ChangeAnalysisRequest(path=path, base=base, head=head, jobs=jobs))
    except GitError as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_USAGE) from exc
    except Exception as exc:
        log.exception("analysis_crashed")
        _err(f"internal error: {exc!r}")
        raise typer.Exit(EXIT_INTERNAL) from exc

    prefix = _path_prefix(path)
    rendered = render(report, output_format, path_prefix=prefix)
    if output is None:
        sys.stdout.write(rendered)
    else:
        _write(output, rendered)
    for fmt, target in extras:
        _write(target, render(report, fmt, path_prefix=prefix))

    if report.config_error and not allow_invalid_config:
        _err(
            "invalid .architecture.yaml (use --allow-invalid-config to ignore):\n"
            f"{report.config_error}"
        )
        raise typer.Exit(EXIT_USAGE)
    raise typer.Exit(exit_code_for(report, fail_on))


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(__version__)


def main() -> None:
    app()
