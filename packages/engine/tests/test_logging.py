"""Tests for structlog configuration."""

from __future__ import annotations

import logging

import pytest
from arch_guardian_engine.logging import configure_logging, get_logger


@pytest.mark.unit
def test_configure_logging_sets_root_level() -> None:
    """configure_logging applies the requested level to the root logger."""
    configure_logging(level="DEBUG", json_logs=True)
    assert logging.getLogger().level == logging.DEBUG


@pytest.mark.unit
def test_get_logger_returns_bound_logger() -> None:
    """get_logger returns a structlog BoundLogger that emits without error."""
    configure_logging(level="INFO", json_logs=False)
    log = get_logger("test")
    log.info("hello", foo="bar")
