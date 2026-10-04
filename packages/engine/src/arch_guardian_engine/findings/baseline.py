"""Keep only findings introduced by a change, given the findings at its base.

Identity is `Finding.fingerprint` (line-independent). Matching is a multiset
difference: if the base has one `<anonymous>` complex function in a file and
the head has two, exactly one is new. Files renamed by the change are mapped
back so moving a file does not resurface its existing debt.

Multi-file findings (dependency cycles) are matched by containment instead:
a head cycle is pre-existing when all its files already formed part of one
base cycle of the same rule. Shrinking a cycle is an improvement and must not
be reported as a new problem; growing it (a new file joins) is.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from arch_guardian_engine.findings.model import MEMBER_FILES_KEY, Finding


def _renamed(finding: Finding, renames: Mapping[str, str]) -> Finding:
    if not any(f in renames for f in finding.files):
        return finding
    location = finding.location.model_copy(
        update={"file": renames.get(finding.location.file, finding.location.file)}
    )
    metadata = dict(finding.metadata)
    if MEMBER_FILES_KEY in metadata:
        metadata[MEMBER_FILES_KEY] = ",".join(sorted(renames.get(f, f) for f in finding.files))
    return finding.model_copy(update={"location": location, "metadata": metadata})


def new_findings(
    head: Iterable[Finding],
    base: Iterable[Finding],
    renames: Mapping[str, str] | None = None,
) -> tuple[Finding, ...]:
    """Findings in `head` that have no counterpart in `base`.

    `renames` maps base paths to head paths (both relative to the analysed root).
    """
    mapped = [_renamed(f, renames or {}) for f in base]
    remaining = Counter(f.fingerprint for f in mapped)
    groups: dict[str, list[frozenset[str]]] = {}
    for f in mapped:
        if MEMBER_FILES_KEY in f.metadata:
            groups.setdefault(f.rule_id, []).append(frozenset(f.files))
    out: list[Finding] = []
    for f in head:
        if MEMBER_FILES_KEY in f.metadata:
            members = frozenset(f.files)
            if not any(members <= g for g in groups.get(f.rule_id, [])):
                out.append(f)
            continue
        fp = f.fingerprint
        if remaining[fp] > 0:
            remaining[fp] -= 1
        else:
            out.append(f)
    return tuple(out)
