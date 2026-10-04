"""Shared fixtures: a throwaway git repository driven from tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
            env=self._env,
        ).stdout.strip()

    def write(self, rel: str, content: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def git_repo(tmp_path: Path) -> GitRepo:
    if shutil.which("git") is None:
        pytest.skip("git binary not on PATH")
    root = tmp_path / "repo"
    root.mkdir()
    return GitRepo(root)
