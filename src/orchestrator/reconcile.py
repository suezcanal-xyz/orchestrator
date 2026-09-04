"""Plan reconciliation algorithm (spec section 18).

    NEW PROMPT + CURRENT PLAN + REPOSITORY REALITY = PLAN UPDATE

A new human prompt is never handed to a worker as-is. It is classified
against the existing docs/PLAN.md and the actual repository, turned into a
dated Change History entry plus zero or more atomic, deduplicated tasks,
merged deterministically into the canonical TaskGraph. The classification
itself is a reasoning task delegated to a worker (spec section 23); parsing,
validation, deduplication and ID assignment are deterministic code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from orchestrator.task_graph import Task, TaskGraph

if TYPE_CHECKING:
    from orchestrator.plan import PlanDocument
    from orchestrator.workers.base import Worker, WorkerResponse

VALID_CLASSIFICATIONS = {
    "NEW_REQUIREMENT",
    "BUG",
    "REGRESSION",
    "CHANGE_TO_EXISTING_REQUIREMENT",
    "PRIORITY_CHANGE",
    "DEFER",
    "REMOVE",
    "QUESTION",
}


class ReconciliationError(Exception):
    pass


@dataclass
class ProposedTask:
    title: str
    acceptance: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    priority: str = "P2"
    files_hint: list[str] = field(default_factory=list)


@dataclass
class ReconcileResult:
    classification: str
    change_history_entry: str
    added_task_ids: list[str] = field(default_factory=list)
    skipped_duplicates: list[str] = field(default_factory=list)
    worker_response: WorkerResponse | None = None


def derive_prefix(project_name: str) -> str:
    """'SeaCommons' -> 'SC', 'republic' -> 'REPU', 'suezcanal.xyz' -> 'SX'."""
    tokens = re.findall(r"[A-Z]+[a-z0-9]*|[a-z0-9]+", project_name)
    if len(tokens) >= 2:
        prefix = "".join(t[0] for t in tokens[:4]).upper()
    elif tokens:
        prefix = tokens[0][:4].upper()
    else:
        prefix = "TASK"
    return prefix or "TASK"


def _extract_json(text: str) -> dict:
    text = text.strip()
    # strip a leading ```json / ``` fence and trailing ``` if the worker wrapped it
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # last resort: grab the outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no JSON object found in worker response")


def _parse_proposal(data: dict) -> tuple[str, str, list[ProposedTask]]:
    classification = data.get("classification")
    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError(f"invalid or missing classification: {classification!r}")
    entry = str(data.get("change_history_entry", "")).strip()
    if not entry:
        raise ValueError("missing change_history_entry")
    raw_tasks = data.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise TypeError("'tasks' must be a list")
    tasks = []
    for t in raw_tasks:
        if not isinstance(t, dict) or not t.get("title"):
            raise ValueError(f"malformed proposed task: {t!r}")
        tasks.append(
            ProposedTask(
                title=str(t["title"]).strip(),
                acceptance=[str(a) for a in t.get("acceptance", [])]
                or ["manually verified"],
                verification=[str(v) for v in t.get("verification", [])]
                or ["manual verification"],
                priority=t.get("priority")
                if t.get("priority") in {"P0", "P1", "P2", "P3"}
                else "P2",
                files_hint=[str(f) for f in t.get("files_hint", [])],
            )
        )
    return classification, entry, tasks


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def merge_proposed_tasks(
    graph: TaskGraph, proposed: list[ProposedTask], prefix: str
) -> tuple[list[str], list[str]]:
    """Deterministic merge: skip titles that already exist as an active task."""
    active_titles = {
        _normalize_title(t.title)
        for t in graph.all()
        if t.status not in {"DONE", "DEFERRED"}
    }
    added: list[str] = []
    skipped: list[str] = []
    for p in proposed:
        norm = _normalize_title(p.title)
        if norm in active_titles:
            skipped.append(p.title)
            continue
        task_id = graph.next_id(prefix)
        graph.add(
            Task(
                id=task_id,
                title=p.title,
                status="READY",
                acceptance=p.acceptance,
                verification=p.verification,
                priority=p.priority,
                files_hint=p.files_hint,
            )
        )
        active_titles.add(norm)
        added.append(task_id)
    return added, skipped


def reconcile(
    *,
    cwd: Path,
    prompt_text: str,
    plan: PlanDocument,
    graph: TaskGraph,
    context_block: str,
    worker: Worker,
    max_retries: int = 1,
) -> ReconcileResult:
    """Ask `worker` to classify prompt_text against plan/context, then merge
    the result into `plan` and `graph` deterministically. Mutates both."""
    plan_text = plan.render()
    last_error: Exception | None = None
    response = None
    for attempt in range(max_retries + 1):
        extra = (
            ""
            if attempt == 0
            else f"\n\nYour previous response could not be parsed ({last_error}). Respond with ONLY the JSON object, no other text."
        )
        response = worker.propose_tasks(
            cwd, prompt_text + extra, plan_text, context_block
        )
        if not response.ok:
            last_error = RuntimeError(response.error or "worker call failed")
            continue
        try:
            data = _extract_json(response.summary)
            classification, entry, proposed = _parse_proposal(data)
            break
        except (ValueError, json.JSONDecodeError) as e:
            last_error = e
    else:
        raise ReconciliationError(
            f"could not reconcile prompt after {max_retries + 1} attempts: {last_error}"
        )

    prefix = derive_prefix(plan.meta.project)
    added, skipped = merge_proposed_tasks(graph, proposed, prefix)

    history_line = entry
    if added:
        history_line += f" Added task(s): {', '.join(added)}."
    if skipped:
        history_line += f" Skipped as already tracked: {', '.join(skipped)}."
    plan.append_change_history(f"{classification}: {history_line}")
    plan.sync_task_section(graph)

    return ReconcileResult(
        classification=classification,
        change_history_entry=entry,
        added_task_ids=added,
        skipped_duplicates=skipped,
        worker_response=response,
    )
