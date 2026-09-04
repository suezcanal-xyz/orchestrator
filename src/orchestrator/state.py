"""Run bootstrap and durable state paths (spec section 14).

Two kinds of state live inside the *target* repository, not in the
orchestrator's own repo:

  <repo>/.orchestrator/state/tasks.json   -- canonical TaskGraph, persists
                                             across runs / days (spec section 8)
  <repo>/.orchestrator/runs/<run-id>/...  -- one immutable folder per run,
                                             the audit trail (spec section 14)

Both live under a repo-root `.orchestrator/` that this module makes sure is
gitignored on first use, so the target repo's own `git status` stays clean
of orchestrator bookkeeping.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.milestone import MilestoneStatus
from orchestrator.task_graph import TaskGraph

ORCH_DIR_NAME = ".orchestrator"
TASKS_STORE_REL = Path("state") / "tasks.json"


def orch_dir(repo_root: Path) -> Path:
    return repo_root / ORCH_DIR_NAME


def ensure_gitignore(repo_root: Path) -> None:
    """Make sure `.orchestrator/` is gitignored in the target repo.

    Idempotent; only appends if the exact line is missing. This is a
    deliberate, visible edit to a tracked file (spec section 23 prefers
    deterministic code, and a silently-mutated .gitignore is exactly the
    kind of surprise a human reviewing `git status` should not hit) -- it
    happens once, at the start of `orchestrator ingest`/`run`, not on every
    worktree creation.
    """
    gi = repo_root / ".gitignore"
    line = f"{ORCH_DIR_NAME}/"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if any(l.strip() == line for l in existing.splitlines()):
        return
    sep = "" if (not existing or existing.endswith("\n")) else "\n"
    gi.write_text(existing + sep + line + "\n", encoding="utf-8")


def new_run_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"run-{ts}-{uuid.uuid4().hex[:6]}"


@dataclass
class RunPaths:
    run_id: str
    root: Path  # <repo>/.orchestrator/runs/<run_id>

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def plan_before(self) -> Path:
        return self.root / "plan-before.md"

    @property
    def plan_after(self) -> Path:
        return self.root / "plan-after.md"

    @property
    def tasks_json(self) -> Path:
        return self.root / "tasks.json"

    @property
    def evidence_dir(self) -> Path:
        return self.root / "evidence"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def diffs_dir(self) -> Path:
        return self.root / "diffs"

    @property
    def tests_dir(self) -> Path:
        return self.root / "tests"

    @property
    def verdict(self) -> Path:
        return self.root / "VERDICT.md"


def init_run(repo_root: Path, run_id: str | None = None) -> RunPaths:
    ensure_gitignore(repo_root)
    run_id = run_id or new_run_id()
    root = orch_dir(repo_root) / "runs" / run_id
    rp = RunPaths(run_id=run_id, root=root)
    for d in (rp.evidence_dir, rp.logs_dir, rp.diffs_dir, rp.tests_dir):
        d.mkdir(parents=True, exist_ok=True)
    return rp


def task_store_path(repo_root: Path) -> Path:
    return orch_dir(repo_root) / TASKS_STORE_REL


def load_task_store(repo_root: Path) -> TaskGraph:
    return TaskGraph.load(task_store_path(repo_root))


def save_task_store(repo_root: Path, graph: TaskGraph) -> None:
    path = task_store_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.save(path)


@dataclass
class RunManifest:
    run_id: str
    repo: str
    prompt: str
    started_at: str
    protected_branch: str
    finished_at: str | None = None
    status: str = MilestoneStatus.IN_PROGRESS.value
    active_milestone: str | None = None
    task_ids: list[str] | None = None
    notes: str = ""
    resumed_from: str | None = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "repo": self.repo,
            "prompt": self.prompt,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "active_milestone": self.active_milestone,
            "task_ids": self.task_ids or [],
            "protected_branch": self.protected_branch,
            "notes": self.notes,
            "resumed_from": self.resumed_from,
        }

    def save(self, run_paths: RunPaths) -> None:
        run_paths.manifest.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, run_paths: RunPaths) -> RunManifest:
        data = json.loads(run_paths.manifest.read_text(encoding="utf-8"))
        return cls(
            run_id=data["run_id"],
            repo=data["repo"],
            prompt=data["prompt"],
            started_at=data["started_at"],
            protected_branch=data.get("protected_branch", "main"),
            finished_at=data.get("finished_at"),
            status=data.get("status", MilestoneStatus.IN_PROGRESS.value),
            active_milestone=data.get("active_milestone"),
            task_ids=data.get("task_ids", []),
            notes=data.get("notes", ""),
            resumed_from=data.get("resumed_from"),
        )


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
