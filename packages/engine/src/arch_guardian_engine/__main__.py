"""CLI entrypoint stub. Real CLI lands in later hitos (F5.x)."""

from __future__ import annotations

import sys

from arch_guardian_engine import __version__
from arch_guardian_engine.logging import configure_logging, get_logger
from arch_guardian_engine.settings import load_settings


def main(argv: list[str] | None = None) -> int:
    """Entry point. Currently prints version + loaded settings summary."""
    argv = argv if argv is not None else sys.argv[1:]
    settings = load_settings()
    configure_logging(
        level=settings.observability.log_level,
        json_logs=settings.observability.log_format == "json",
    )
    log = get_logger("arch_guardian_engine")
    log.info(
        "engine_started",
        version=__version__,
        environment=settings.environment,
        primary_model=settings.llm.primary_model,
    )
    if argv and argv[0] in {"-v", "--version"}:
        print(__version__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
