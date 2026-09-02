"""Orchestration engine (spec section 1, 15, 16, 22).

Ties the deterministic pieces together into the daily workflow:

    read repo -> read PLAN.md -> reconcile prompt -> update PLAN.md
    -> schedule tasks -> execute (worker per task, isolated worktree)
    -> verify -> debug on failure -> update PLAN.md -> VERDICT

`run()` is the `orchestrator run --prompt "..."` shortcut (ingest + plan +
execution + verification in one pass). Each piece is also exposed on its
own (`ingest`, `build_verdict`) for the narrower CLI subcommands.

Within one batch of mutually-independent, non-file-overlapping tasks
(TaskGraph.parallelizable_batches, spec section 7), tasks run concurrently
via a thread pool -- safe because each task is fully isolated in its own
git worktree and the actual work happens in subprocess calls (which release
the GIL while running), so this gives genuine concurrent Codex/Claude
execution, not just an isolation mechanism that happens not to be used.
"""

from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator import context as context_mod
from orchestrator import evidence
from orchestrator import extensions
from orchestrator import git
from orchestrator import plan as plan_mod
from orchestrator import policy as policy_mod
from orchestrator import reconcile as reconcile_mod
from orchestrator import state
from orchestrator.debugger import DEFAULT_MAX_DEBUG_ATTEMPTS, run_debug_loop
from orchestrator.milestone import CriterionResult, Verdict
from orchestrator.task_graph import Task, TaskGraph
from orchestrator.verifier import VerificationResult, overall_passed, run_verification
from orchestrator.workers.base import Worker

PLAN_PATH_REL = Path("docs") / "PLAN.md"

# Character budget for the repo-map portion of a per-task context block.
# Tunable per project via the `context_char_budget` policy (private layer).
DEFAULT_CONTEXT_CHAR_BUDGET = 2500


def plan_path(repo: Path) -> Path:
    return repo / PLAN_PATH_REL


def load_or_create_plan(repo: Path, project_name: str | None = None) -> plan_mod.PlanDocument:
    p = plan_path(repo)
    if p.exists():
        return plan_mod.load(p)
    return plan_mod.new_plan(project_name or repo.name)


def _bullets_of(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            out.append(line[2:].strip())
    return out


@dataclass
class IngestResult:
    plan: plan_mod.PlanDocument
    graph: TaskGraph
    reconcile_result: reconcile_mod.ReconcileResult


def inspect(repo: Path) -> context_mod.RepoContext:
    return context_mod.build_context(repo)


def ingest(repo: Path, prompt_text: str, worker: Worker) -> IngestResult:
    """Accept one human prompt, reconcile it into docs/PLAN.md + the task store."""
    state.ensure_gitignore(repo)
    doc = load_or_create_plan(repo)
    graph = state.load_task_store(repo)
    ctx = context_mod.build_context(repo)
    result = reconcile_mod.reconcile(
        cwd=repo,
        prompt_text=prompt_text,
        plan=doc,
        graph=graph,
        context_block=context_mod.with_providers(ctx, repo),
        worker=worker,
    )
    doc.save(plan_path(repo))
    state.save_task_store(repo, graph)
    extensions.run_hooks("reconcile_done", repo=repo, prompt=prompt_text, result=result)
    return IngestResult(plan=doc, graph=graph, reconcile_result=result)


@dataclass
class TaskOutcome:
    task_id: str
    status: str  # "DONE" | "BLOCKED"
    worktree: Path | None
    branch: str | None
    commit: str | None
    verification: list[VerificationResult] = field(default_factory=list)
    debug_attempts: int = 0
    reason: str = ""


@dataclass
class RunResult:
    manifest: state.RunManifest
    run_paths: state.RunPaths
    plan: plan_mod.PlanDocument
    graph: TaskGraph
    task_outcomes: list[TaskOutcome] = field(default_factory=list)
    verdict: Verdict | None = None


def execute_task(
    *,
    repo: Path,
    run_id: str,
    run_paths: state.RunPaths,
    task: Task,
    context_block: str,
    implement_worker: Worker,
    debug_workers: list[Worker],
    max_debug_attempts: int = DEFAULT_MAX_DEBUG_ATTEMPTS,
    verification_timeout: int = 600,
) -> TaskOutcome:
    """Implement one task in its own worktree, verify it, debug on failure.

    The orchestrator -- not the worker -- performs the git commit after each
    call returns (spec section 23), so there is always a known commit for
    evidence regardless of what the model did inside the worktree.

    Fires task_started / task_implemented / task_verified /
    task_debug_attempt / task_done / task_blocked hooks (see
    `extensions.register_hook`) as each phase completes, so a caller (the
    CLI's live progress printer, a notification integration, ...) sees
    progress as it happens rather than only once the whole task returns.
    Called from a worker thread when part of a parallel batch -- hook
    functions must be safe to call from multiple threads concurrently.
    """
    task.status = "IN_PROGRESS"
    wt = git.create_worktree(repo, run_id, task.id)
    task.assigned_worktree = str(wt.path)
    task.worker = implement_worker.name
    protected = git.default_branch(repo)
    extensions.run_hooks("task_started", task=task, worker=implement_worker.name)

    response = implement_worker.implement(wt.path, task, context_block)
    evidence.save_worker_response(run_paths, task.id, "implement", response)

    commit = git.commit_all(wt.path, f"{task.id}: {task.title}\n\nImplemented by {implement_worker.name}.")
    evidence.save_diff(run_paths, task.id, git.diff(wt.path, base_ref=protected))
    extensions.run_hooks("task_implemented", task=task, worker=implement_worker.name, response=response, commit=commit)

    results = run_verification(
        task.verification, wt.path, timeout_per_command=verification_timeout,
        commit=commit, worker=implement_worker.name, attempt=1,
    )
    evidence.save_verification(run_paths, task.id, results)
    passed = overall_passed(results)
    extensions.run_hooks("task_verified", task=task, results=results, passed=passed, attempt=1)

    debug_attempts = 0
    if not passed:
        outcome = run_debug_loop(
            cwd=wt.path,
            task=task,
            initial_results=results,
            verification_commands=task.verification,
            debugger_workers=debug_workers or [implement_worker],
            run_verification_fn=lambda: run_verification(
                task.verification, wt.path, timeout_per_command=verification_timeout, worker="debug"
            ),
            get_diff_fn=lambda: git.diff(wt.path, base_ref=protected),
            commit_fn=lambda msg: git.commit_all(wt.path, msg),
            max_attempts=max_debug_attempts,
            on_attempt=lambda record: extensions.run_hooks("task_debug_attempt", task=task, record=record),
        )
        for i, a in enumerate(outcome.attempts, start=1):
            evidence.save_worker_response(run_paths, task.id, f"debug-{i}", a.debugger_response)
            evidence.save_verification(run_paths, task.id, a.results_after)
        debug_attempts = len(outcome.attempts)
        results = outcome.final_results
        commit = git.head_commit(wt.path)
        evidence.save_diff(run_paths, task.id, git.diff(wt.path, base_ref=protected))
        if outcome.status != "FIXED":
            task.status = "BLOCKED"
            task.attempts += 1
            blocked_outcome = TaskOutcome(
                task_id=task.id, status="BLOCKED", worktree=wt.path, branch=wt.branch, commit=commit,
                verification=results, debug_attempts=debug_attempts, reason=outcome.reason,
            )
            extensions.run_hooks("task_blocked", task=task, outcome=blocked_outcome)
            return blocked_outcome

    task.status = "DONE"
    task.attempts += 1
    done_outcome = TaskOutcome(
        task_id=task.id, status="DONE", worktree=wt.path, branch=wt.branch, commit=commit,
        verification=results, debug_attempts=debug_attempts, reason="verification passed",
    )
    extensions.run_hooks("task_done", task=task, outcome=done_outcome)
    return done_outcome


def build_verdict(
    repo: Path, doc: plan_mod.PlanDocument, graph: TaskGraph, timeout_per_command: int = 600
) -> Verdict:
    """Compare repository state against milestone acceptance criteria (spec section 19).

    Each line under `## Acceptance Criteria` is matched positionally against
    a line under `## Verification Commands` and the command is actually run.
    If the two lists are not the same length (no verification command
    authored yet for every criterion), falls back to one criterion per
    non-deferred task, proved by that task's own DONE/BLOCKED status --
    still evidence-based, just coarser.
    """
    criteria_lines = _bullets_of(doc.get_section("Acceptance Criteria"))
    verification_lines = _bullets_of(doc.get_section("Verification Commands"))
    verdict = Verdict(project=doc.meta.project, target_version=doc.meta.target_version)
    if criteria_lines and len(criteria_lines) == len(verification_lines):
        for desc, cmd in zip(criteria_lines, verification_lines):
            r = run_verification([cmd], repo, timeout_per_command=timeout_per_command)[0]
            verdict.criteria.append(
                CriterionResult(description=desc, passed=r.passed, detail="" if r.passed else cmd)
            )
    else:
        for t in sorted(graph.all(), key=lambda t: t.id):
            if t.status == "DEFERRED":
                continue
            verdict.criteria.append(CriterionResult(description=f"{t.id}: {t.title}", passed=t.status == "DONE"))
    return verdict


def _assign_workers(tasks: list[Task], workers: list[Worker]) -> dict[str, Worker]:
    return {t.id: w for t, w in zip(tasks, itertools.cycle(workers))}


def run(
    *,
    repo: Path,
    prompt_text: str | None,
    implement_workers: list[Worker],
    debug_workers: list[Worker] | None = None,
    max_debug_attempts: int = DEFAULT_MAX_DEBUG_ATTEMPTS,
    verification_timeout: int = 600,
) -> RunResult:
    """ingest + plan + execution + verification in one pass (spec section 16)."""
    if not implement_workers:
        raise ValueError("run() requires at least one implement worker")

    state.ensure_gitignore(repo)
    run_paths = state.init_run(repo)
    started_at = state.now_iso()

    doc = load_or_create_plan(repo)
    graph = state.load_task_store(repo)
    run_paths.plan_before.write_text(doc.render(), encoding="utf-8")

    ctx = context_mod.build_context(repo)
    project = doc.meta.project
    char_budget = policy_mod.effective_int(
        "context_char_budget", project, DEFAULT_CONTEXT_CHAR_BUDGET
    )
    run_wide_context = context_mod.with_providers(ctx, repo)

    if prompt_text:
        reconcile_result = reconcile_mod.reconcile(
            cwd=repo, prompt_text=prompt_text, plan=doc, graph=graph,
            context_block=run_wide_context, worker=implement_workers[0],
        )
        extensions.run_hooks("reconcile_done", repo=repo, prompt=prompt_text, result=reconcile_result)

    batches = graph.parallelizable_batches()
    ordered_tasks = [t for batch in batches for t in batch]
    assignment = _assign_workers(ordered_tasks, implement_workers)

    extensions.run_hooks(
        "run_started", repo=repo, run_id=run_paths.run_id, prompt=prompt_text,
        task_ids=[t.id for t in ordered_tasks], batch_count=len(batches),
    )

    outcomes: list[TaskOutcome] = []
    for batch in batches:
        with ThreadPoolExecutor(max_workers=max(1, len(batch))) as pool:
            futures = {
                pool.submit(
                    execute_task,
                    repo=repo,
                    run_id=run_paths.run_id,
                    run_paths=run_paths,
                    task=task,
                    context_block=context_mod.focused_context(
                        ctx, task.files_hint, char_budget=char_budget, repo_path=repo
                    ),
                    implement_worker=assignment[task.id],
                    debug_workers=[w for w in implement_workers if w is not assignment[task.id]] + (debug_workers or []),
                    max_debug_attempts=max_debug_attempts,
                    verification_timeout=verification_timeout,
                ): task
                for task in batch
            }
            for fut in as_completed(futures):
                outcomes.append(fut.result())

    outcomes.sort(key=lambda o: o.task_id)

    state.save_task_store(repo, graph)
    doc.sync_task_section(graph)

    verdict = build_verdict(repo, doc, graph, timeout_per_command=verification_timeout)
    doc.meta.status = verdict.result_status
    doc.save(plan_path(repo))
    run_paths.plan_after.write_text(doc.render(), encoding="utf-8")
    evidence.write_verdict(run_paths, verdict.render())

    manifest = state.RunManifest(
        run_id=run_paths.run_id,
        repo=str(repo),
        prompt=prompt_text or "",
        started_at=started_at,
        protected_branch=git.default_branch(repo),
        finished_at=state.now_iso(),
        status=verdict.result_status.value,
        active_milestone=doc.meta.active_milestone,
        task_ids=[o.task_id for o in outcomes],
    )
    manifest.save(run_paths)
    extensions.run_hooks("run_finished", manifest=manifest, verdict=verdict, run_paths=run_paths)

    return RunResult(
        manifest=manifest, run_paths=run_paths, plan=doc, graph=graph,
        task_outcomes=outcomes, verdict=verdict,
    )


def status(repo: Path) -> dict:
    """Summary for `orchestrator status` (spec section 16): no execution."""
    doc = load_or_create_plan(repo)
    graph = state.load_task_store(repo)
    by_status: dict[str, int] = {}
    for t in graph.all():
        by_status[t.status] = by_status.get(t.status, 0) + 1
    return {
        "project": doc.meta.project,
        "current_version": doc.meta.current_version,
        "target_version": doc.meta.target_version,
        "active_milestone": doc.meta.active_milestone,
        "status": doc.meta.status.value,
        "tasks_by_status": by_status,
        "total_tasks": len(graph),
    }
