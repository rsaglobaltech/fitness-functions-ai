"""analyze_changes against a real git history."""

from __future__ import annotations

import pytest
from arch_guardian_engine.analyzer import ChangeAnalysisRequest, analyze_changes
from arch_guardian_engine.diff import GitError

from tests.conftest import GitRepo

COMPLEX = "def {name}(x):\n" + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
CYCLE_A = "from b import B\nclass A: ...\n"
CYCLE_B = "from a import A\nclass B: ...\n"


@pytest.fixture
def repo_with_debt(git_repo: GitRepo) -> GitRepo:
    git_repo.write("a.py", CYCLE_A)
    git_repo.write("b.py", CYCLE_B)
    git_repo.write("legacy.py", COMPLEX.format(name="old"))
    git_repo.commit("base with debt")
    git_repo.git("checkout", "-q", "-b", "feature")
    return git_repo


@pytest.mark.integration
def test_full_scan_reports_existing_debt(repo_with_debt: GitRepo) -> None:
    report = analyze_changes(ChangeAnalysisRequest(path=repo_with_debt.root))
    assert len(report.findings) == 2
    assert report.base_ref is None


@pytest.mark.integration
def test_only_new_findings_are_reported(repo_with_debt: GitRepo) -> None:
    repo_with_debt.write("legacy.py", "\n\n" + COMPLEX.format(name="old"))  # shifted lines
    repo_with_debt.write("new.py", COMPLEX.format(name="fresh"))
    repo_with_debt.commit("feature")

    report = analyze_changes(ChangeAnalysisRequest(path=repo_with_debt.root, base="main"))

    assert [f.location.symbol for f in report.findings] == ["fresh"]
    assert report.baseline_count == 2
    assert report.base_ref == "main"


@pytest.mark.integration
def test_uncommitted_working_tree_changes_are_analysed(repo_with_debt: GitRepo) -> None:
    repo_with_debt.write("wip.py", COMPLEX.format(name="wip"))
    report = analyze_changes(ChangeAnalysisRequest(path=repo_with_debt.root, base="main"))
    assert [f.location.symbol for f in report.findings] == ["wip"]


@pytest.mark.integration
def test_renaming_a_file_does_not_resurface_its_debt(repo_with_debt: GitRepo) -> None:
    repo_with_debt.git("mv", "legacy.py", "moved.py")
    repo_with_debt.commit("rename")
    report = analyze_changes(ChangeAnalysisRequest(path=repo_with_debt.root, base="main"))
    assert report.findings == ()


@pytest.mark.integration
def test_explicit_head_ref_and_subdirectory(git_repo: GitRepo) -> None:
    git_repo.write("svc/x.py", "x = 1\n")
    git_repo.commit("base")
    git_repo.git("checkout", "-q", "-b", "feature")
    git_repo.write("svc/y.py", COMPLEX.format(name="y"))
    git_repo.write("other/z.py", COMPLEX.format(name="z"))
    git_repo.commit("feature")
    git_repo.git("checkout", "-q", "main")  # working tree is NOT the head

    report = analyze_changes(
        ChangeAnalysisRequest(path=git_repo.root / "svc", base="main", head="feature")
    )
    assert [(f.location.file, f.location.symbol) for f in report.findings] == [("y.py", "y")]
    assert report.repo == str((git_repo.root / "svc").resolve())
    assert git_repo.git("worktree", "list").count("\n") == 0  # temp worktrees cleaned


@pytest.mark.integration
def test_unknown_base_ref_raises_git_error(repo_with_debt: GitRepo) -> None:
    with pytest.raises(GitError):
        analyze_changes(ChangeAnalysisRequest(path=repo_with_debt.root, base="nope"))


@pytest.mark.integration
def test_option_like_ref_is_rejected(repo_with_debt: GitRepo) -> None:
    with pytest.raises(GitError, match="invalid ref"):
        analyze_changes(ChangeAnalysisRequest(path=repo_with_debt.root, base="--output=/tmp/x"))
