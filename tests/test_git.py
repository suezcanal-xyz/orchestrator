import subprocess
from pathlib import Path

import pytest

from orchestrator import git


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)
    return path


@pytest.fixture
def repo(tmp_path):
    return _init_repo(tmp_path / "demo")


def test_is_git_repo(repo):
    assert git.is_git_repo(repo)
    assert not git.is_git_repo(repo.parent)


def test_default_branch_falls_back_to_local_main(repo):
    assert git.default_branch(repo) == "main"


def test_create_worktree_and_isolate_changes(repo):
    wt = git.create_worktree(repo, run_id="run1", task_id="SC-001")
    assert wt.branch == "orchestrator/run1/SC-001"
    assert wt.path.exists()

    (wt.path / "new_file.txt").write_text("hi\n", encoding="utf-8")
    assert git.has_changes(wt.path)

    # main worktree (the original repo) must have no tracked-file changes.
    # (.orchestrator/worktrees/... shows up as untracked until the bootstrap
    # step gitignores it -- see state.py -- so we only assert on tracked state.)
    tracked_changes = [
        line
        for line in git.status_porcelain(repo).splitlines()
        if not line.startswith("??")
    ]
    assert tracked_changes == []
    assert not (repo / "new_file.txt").exists()


def test_commit_all_returns_sha(repo):
    wt = git.create_worktree(repo, run_id="run1", task_id="SC-002")
    (wt.path / "x.txt").write_text("data\n", encoding="utf-8")
    sha = git.commit_all(wt.path, "task SC-002: add x.txt")
    assert sha and len(sha) == 40
    assert "x.txt" in git.files_changed(wt.path, base_ref="main")


def test_commit_all_returns_none_when_nothing_changed(repo):
    wt = git.create_worktree(repo, run_id="run1", task_id="SC-003")
    assert git.commit_all(wt.path, "no-op") is None


def test_assert_not_protected_rejects_main(repo):
    with pytest.raises(git.ProtectedBranchError):
        git.assert_not_protected(repo, "main")


def test_two_worktrees_are_independent(repo):
    wt_a = git.create_worktree(repo, run_id="run1", task_id="A")
    wt_b = git.create_worktree(repo, run_id="run1", task_id="B")
    (wt_a.path / "a.txt").write_text("a\n", encoding="utf-8")
    (wt_b.path / "b.txt").write_text("b\n", encoding="utf-8")
    git.commit_all(wt_a.path, "add a")
    git.commit_all(wt_b.path, "add b")
    assert (wt_a.path / "a.txt").exists()
    assert not (wt_a.path / "b.txt").exists()
    assert (wt_b.path / "b.txt").exists()
    assert not (wt_b.path / "a.txt").exists()


def test_remove_worktree(repo):
    wt = git.create_worktree(repo, run_id="run1", task_id="SC-004")
    git.remove_worktree(wt)
    assert wt.path not in git.list_worktrees(repo)
