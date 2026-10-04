"""Tests for repo-relative glob matching."""

from __future__ import annotations

import pytest
from arch_guardian_engine.paths import matches_glob


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("src/legacy/a.py", "src/legacy/**", True),
        ("src/legacy/deep/b/c.py", "src/legacy/**", True),
        ("src/legacyx/a.py", "src/legacy/**", False),
        ("src/a.py", "src/*.py", True),
        ("src/a/b.py", "src/*.py", False),
        ("src/a/b.py", "src/**/*.py", True),
        ("src/b.py", "src/**/*.py", True),
        ("src/domain/x.ts", "./src/domain/**", True),
        ("src/a1.py", "src/a?.py", True),
        ("src/a/1.py", "src/a?.py", False),
        ("src/a+b.py", "src/a+b.py", True),
    ],
)
def test_matches_glob(path: str, pattern: str, expected: bool) -> None:
    assert matches_glob(path, pattern) is expected
