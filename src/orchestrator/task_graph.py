"""Structured task representation and dependency DAG (spec section 8, 7)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class TaskGraphError(Exception):
    pass


class CycleError(TaskGraphError):
    pass


VALID_STATUSES = {
    "NEEDS_TRIAGE",
    "READY",
    "IN_PROGRESS",
    "IN_REVIEW",
    "BLOCKED",
    "DONE",
    "DEFERRED",
}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}


@dataclass
class Task:
    id: str
    title: str
    status: str = "NEEDS_TRIAGE"
    depends_on: list[str] = field(default_factory=list)
    files_hint: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    priority: str = "P2"
    worker: str | None = None
    assigned_worktree: str | None = None
    attempts: int = 0
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise TaskGraphError(f"{self.id}: invalid status {self.status!r}")
        if self.priority not in VALID_PRIORITIES:
            raise TaskGraphError(f"{self.id}: invalid priority {self.priority!r}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "depends_on": list(self.depends_on),
            "files_hint": list(self.files_hint),
            "acceptance": list(self.acceptance),
            "verification": list(self.verification),
            "priority": self.priority,
            "worker": self.worker,
            "assigned_worktree": self.assigned_worktree,
            "attempts": self.attempts,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            id=data["id"],
            title=data["title"],
            status=data.get("status", "NEEDS_TRIAGE"),
            depends_on=list(data.get("depends_on", [])),
            files_hint=list(data.get("files_hint", [])),
            acceptance=list(data.get("acceptance", [])),
            verification=list(data.get("verification", [])),
            priority=data.get("priority", "P2"),
            worker=data.get("worker"),
            assigned_worktree=data.get("assigned_worktree"),
            attempts=int(data.get("attempts", 0)),
            notes=data.get("notes", ""),
        )


class TaskGraph:
    """Holds a set of tasks and answers DAG-shaped questions about them.

    This is deterministic bookkeeping code (spec section 23) -- no model calls here.
    """

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        for t in tasks or []:
            self.add(t)

    def add(self, task: Task) -> None:
        self._tasks[task.id] = task

    def get(self, task_id: str) -> Task:
        return self._tasks[task_id]

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._tasks

    def __iter__(self):
        return iter(self._tasks.values())

    def __len__(self) -> int:
        return len(self._tasks)

    def all(self) -> list[Task]:
        return list(self._tasks.values())

    def validate(self) -> None:
        """Raise if any dependency is dangling or a cycle exists."""
        for task in self._tasks.values():
            for dep in task.depends_on:
                if dep not in self._tasks:
                    raise TaskGraphError(f"{task.id} depends on unknown task {dep!r}")
        self.topological_order()

    def topological_order(self) -> list[str]:
        """Kahn's algorithm. Raises CycleError on a cycle."""
        indegree = {tid: 0 for tid in self._tasks}
        for task in self._tasks.values():
            for dep in task.depends_on:
                indegree[task.id] = indegree.get(task.id, 0) + 1
        ready = [tid for tid, deg in indegree.items() if deg == 0]
        ready.sort()
        order: list[str] = []
        remaining = {tid: set(t.depends_on) for tid, t in self._tasks.items()}
        while ready:
            ready.sort()
            current = ready.pop(0)
            order.append(current)
            for tid, deps in remaining.items():
                if current in deps:
                    deps.discard(current)
                    if not deps and tid not in order and tid not in ready:
                        ready.append(tid)
        if len(order) != len(self._tasks):
            stuck = sorted(set(self._tasks) - set(order))
            raise CycleError(f"dependency cycle involving: {stuck}")
        return order

    def ready_tasks(self) -> list[Task]:
        """Tasks whose dependencies are all DONE and are themselves READY."""
        done = {tid for tid, t in self._tasks.items() if t.status == "DONE"}
        out = []
        for task in self._tasks.values():
            if task.status != "READY":
                continue
            if all(dep in done for dep in task.depends_on):
                out.append(task)
        return out

    @staticmethod
    def _norm_hint(p: str) -> str:
        """Normalise a files_hint entry so `./src/x.py`, `src\\x.py` and
        `src/x.py` compare equal."""
        return p.replace("\\", "/").lstrip("./").rstrip("/")

    @classmethod
    def files_overlap(cls, a: Task, b: Task) -> bool:
        """Conservative overlap check: shared hinted path (any spelling) or
        one is a directory prefix of the other."""
        return cls.shared_files(a, b) != []

    @classmethod
    def shared_files(cls, a: Task, b: Task) -> list[str]:
        """Every hinted path where `a` and `b` overlap, normalised."""
        out: list[str] = []
        for pa in a.files_hint:
            for pb in b.files_hint:
                na, nb = cls._norm_hint(pa), cls._norm_hint(pb)
                if na == nb or na.startswith(nb + "/") or nb.startswith(na + "/"):
                    shortest = na if len(na) <= len(nb) else nb
                    if shortest not in out:
                        out.append(shortest)
        return out

    def likely_overlaps(self, tasks: "list[Task] | None" = None) -> list[tuple[str, str, str]]:
        """Pairs of tasks (from `tasks`, default all READY) whose files_hint
        overlap -- (id_a, id_b, shared_path). The scheduler serialises
        these into different batches; this list is what a run should warn
        the human about, because the two branches still have to be
        integrated against the same file."""
        pool = sorted(tasks if tasks is not None else self.ready_tasks(), key=lambda t: t.id)
        out: list[tuple[str, str, str]] = []
        for i, a in enumerate(pool):
            for b in pool[i + 1:]:
                for path in self.shared_files(a, b):
                    out.append((a.id, b.id, path))
        return out

    def parallelizable_batches(self) -> list[list[Task]]:
        """Group ready tasks into batches that can safely run in parallel worktrees.

        Two ready tasks land in the same batch only if neither depends on the
        other (both are dependency-free at this point, by construction of
        ready_tasks) and their files_hint do not overlap. Tasks with no
        files_hint declared are treated as potentially overlapping with
        everything and are scheduled alone (conservative default).
        """
        ready = sorted(self.ready_tasks(), key=lambda t: (t.priority, t.id))
        batches: list[list[Task]] = []
        for task in ready:
            placed = False
            if task.files_hint:
                for batch in batches:
                    if all(
                        other.files_hint and not self.files_overlap(task, other)
                        for other in batch
                    ):
                        batch.append(task)
                        placed = True
                        break
            if not placed:
                batches.append([task])
        return batches

    def to_list(self) -> list[dict]:
        return [t.to_dict() for t in self._tasks.values()]

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_list(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "TaskGraph":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Task.from_dict(d) for d in data])

    def next_id(self, prefix: str) -> str:
        existing = [
            int(t.id.split("-")[-1])
            for t in self._tasks.values()
            if t.id.startswith(prefix + "-") and t.id.split("-")[-1].isdigit()
        ]
        n = max(existing, default=0) + 1
        return f"{prefix}-{n:03d}"
