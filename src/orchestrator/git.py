"""Git worktree isolation (spec section 7, 17).

All agent work happens in an isolated worktree on a branch named
`orchestrator/<run-id>/<task-id>`, never on the repository's protected
(default) branch. This module is deterministic, thin wrapping of the `git`
CLI -- no model calls here (spec section 23).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

PROTECTED_BRANCH_NAMES = {"main", "master"}


class GitError(Exception):
    pass


class ProtectedBranchError(GitError):
    pass


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed in {cwd} (exit {proc.returncode}):\n{proc.stderr}"
        )
    return proc


def is_git_repo(path: Path) -> bool:
    proc = _run(["rev-parse", "--is-inside-work-tree"], cwd=path, check=False)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def repo_root(path: Path) -> Path:
    proc = _run(["rev-parse", "--show-toplevel"], cwd=path)
    return Path(proc.stdout.strip())


def current_branch(path: Path) -> str:
    proc = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    return proc.stdout.strip()


def default_branch(path: Path) -> str:
    """Best-effort detection of the protected/default branch.

    Tries origin/HEAD first, then falls back to whichever of main/master
    exists locally, then to the current branch as a last resort.
    """
    proc = _run(
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=path, check=False
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().split("/", 1)[-1]
    branches = _run(["branch", "--list"], cwd=path, check=False).stdout
    for name in PROTECTED_BRANCH_NAMES:
        if any(
            line.strip().lstrip("* ").strip() == name for line in branches.splitlines()
        ):
            return name
    return current_branch(path)


def assert_not_protected(path: Path, branch: str) -> None:
    protected = PROTECTED_BRANCH_NAMES | {default_branch(path)}
    if branch in protected:
        raise ProtectedBranchError(
            f"refusing to operate directly on protected branch {branch!r}"
        )


def branch_name(run_id: str, task_id: str) -> str:
    return f"orchestrator/{run_id}/{task_id}"


@dataclass
class Worktree:
    path: Path
    branch: str
    repo_root: Path


def create_worktree(
    repo: Path, run_id: str, task_id: str, base_ref: str | None = None
) -> Worktree:
    """Create an isolated worktree on a new orchestrator/<run>/<task> branch.

    Worktrees are created as sibling directories of the repo, under
    `<repo>/.orchestrator/worktrees/<run_id>/<task_id>`, so they are never
    nested inside a path git itself is tracking.
    """
    root = repo_root(repo)
    base = base_ref or default_branch(root)
    branch = branch_name(run_id, task_id)
    assert_not_protected(
        root, branch
    )  # defensive; branch is always namespaced, never protected

    wt_dir = root / ".orchestrator" / "worktrees" / run_id / task_id
    wt_dir.parent.mkdir(parents=True, exist_ok=True)
    if wt_dir.exists():
        raise GitError(f"worktree path already exists: {wt_dir}")

    existing_branch = _run(
        ["branch", "--list", branch], cwd=root, check=False
    ).stdout.strip()
    if existing_branch:
        _run(["worktree", "add", str(wt_dir), branch], cwd=root)
    else:
        _run(["worktree", "add", "-b", branch, str(wt_dir), base], cwd=root)

    return Worktree(path=wt_dir, branch=branch, repo_root=root)


@dataclass
class IntegrationResult:
    worktree: Worktree
    merged: list[str]  # task branches that merged cleanly
    conflicted: list[str]  # task branches that did not (recorded, then skipped)


def create_integration_worktree(
    repo: Path, run_id: str, task_branches: list[str], base_ref: str | None = None
) -> IntegrationResult:
    """A scratch worktree off the protected branch with every given task
    branch merged in -- the combined state a human would get by merging all
    of this run's completed work.

    Milestone acceptance must be judged against what the run actually
    produced (spec section 19), not against the untouched base branch:
    task work lives only in per-task worktrees and nothing is merged in v0
    (spec section 22 step 17), so running the acceptance commands in `repo`
    itself always fails. A branch that does not merge cleanly is rolled
    back and recorded in `conflicted` -- overlapping parallel work the
    scheduler should have kept apart (spec section 7), surfaced rather than
    crashed on.
    """
    root = repo_root(repo)
    base = base_ref or default_branch(root)
    branch = f"orchestrator/{run_id}/_integration"
    wt_dir = root / ".orchestrator" / "worktrees" / run_id / "_integration"
    wt_dir.parent.mkdir(parents=True, exist_ok=True)
    if wt_dir.exists():
        _run(["worktree", "remove", "--force", str(wt_dir)], cwd=root, check=False)
    _run(["branch", "-D", branch], cwd=root, check=False)
    _run(["worktree", "add", "-b", branch, str(wt_dir), base], cwd=root)

    merged: list[str] = []
    conflicted: list[str] = []
    for tb in task_branches:
        p = _run(
            ["merge", "--no-ff", "-m", f"integrate {tb}", tb], cwd=wt_dir, check=False
        )
        if p.returncode == 0:
            merged.append(tb)
        else:
            _run(["merge", "--abort"], cwd=wt_dir, check=False)
            conflicted.append(tb)
    return IntegrationResult(
        worktree=Worktree(path=wt_dir, branch=branch, repo_root=root),
        merged=merged,
        conflicted=conflicted,
    )


def remove_worktree(wt: Worktree, force: bool = True) -> None:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(wt.path))
    _run(args, cwd=wt.repo_root, check=False)


def list_worktrees(repo: Path) -> list[Path]:
    root = repo_root(repo)
    proc = _run(["worktree", "list", "--porcelain"], cwd=root)
    paths = []
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]))
    return paths


def status_porcelain(wt_path: Path) -> str:
    return _run(["status", "--porcelain"], cwd=wt_path).stdout


def has_changes(wt_path: Path) -> bool:
    return bool(status_porcelain(wt_path).strip())


def diff(wt_path: Path, base_ref: str | None = None) -> str:
    if base_ref:
        return _run(["diff", base_ref, "--"], cwd=wt_path).stdout
    return _run(["diff", "HEAD", "--"], cwd=wt_path).stdout


def diff_stat(wt_path: Path, base_ref: str | None = None) -> str:
    args = ["diff", "--stat"]
    if base_ref:
        args.append(base_ref)
    return _run(args, cwd=wt_path).stdout


def commit_all(wt_path: Path, message: str, allow_empty: bool = False) -> str | None:
    """Stage and commit everything in the worktree. Returns the new commit sha, or
    None if there was nothing to commit and allow_empty is False."""
    _run(["add", "-A"], cwd=wt_path)
    if not allow_empty and not has_changes(wt_path):
        staged = _run(["diff", "--cached", "--stat"], cwd=wt_path).stdout
        if not staged.strip():
            return None
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    _run(args, cwd=wt_path)
    return _run(["rev-parse", "HEAD"], cwd=wt_path).stdout.strip()


def head_commit(wt_path: Path) -> str:
    return _run(["rev-parse", "HEAD"], cwd=wt_path).stdout.strip()


def files_changed(wt_path: Path, base_ref: str | None = None) -> list[str]:
    args = ["diff", "--name-only"]
    if base_ref:
        args.append(base_ref)
    else:
        args.append("HEAD")
    out = _run(args, cwd=wt_path).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]
