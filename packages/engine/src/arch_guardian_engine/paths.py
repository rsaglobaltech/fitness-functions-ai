"""Repo-relative path glob matching shared by exceptions and layer rules.

Why not `fnmatch` / `PurePath.match`:
    - `fnmatch` lets `*` cross `/`, so `src/*.py` would match `src/a/b.py`.
    - `PurePath.match` on 3.12 has no `**` support (`full_match` is 3.13+).

Semantics (gitignore-like, always on POSIX-style relative paths):
    - `*`   matches any run of characters except `/`.
    - `?`   matches one character except `/`.
    - `**`  as a whole segment matches zero or more directories.
    - A pattern ending in `/**` matches everything below that directory.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path, PurePosixPath


@lru_cache(maxsize=512)
def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a repo-relative glob into an anchored regex."""
    pat = pattern.strip()
    if pat.startswith("./"):
        pat = pat[2:]
    pat = pat.lstrip("/")
    segments = pat.split("/")
    parts: list[str] = []
    for i, seg in enumerate(segments):
        last = i == len(segments) - 1
        if seg == "**":
            # `a/**` → everything under a; `a/**/b` → zero or more dirs between.
            parts.append(".*" if last else "(?:[^/]+/)*")
            continue
        buf = []
        for ch in seg:
            if ch == "*":
                buf.append("[^/]*")
            elif ch == "?":
                buf.append("[^/]")
            else:
                buf.append(re.escape(ch))
        parts.append("".join(buf) + ("" if last else "/"))
    return re.compile("".join(parts) + r"\Z")


def to_posix_relative(path: str | Path) -> str:
    """Normalise a path to the POSIX relative form patterns are matched against."""
    text = PurePosixPath(Path(path).as_posix()).as_posix()
    return text[2:] if text.startswith("./") else text


def matches_glob(path: str | Path, pattern: str) -> bool:
    """True if the repo-relative `path` matches the glob `pattern`."""
    return glob_to_regex(pattern).match(to_posix_relative(path)) is not None


def matches_any(path: str | Path, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(matches_glob(path, p) for p in patterns)


def repo_uri(prefix: str, file: str) -> str:
    """Join an analysed-root-relative `file` onto the root's repo-relative `prefix`."""
    prefix = prefix.strip("/")
    return f"{prefix}/{file}" if prefix and prefix != "." else file
