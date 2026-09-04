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
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator import context as context_mod
from orchestrator import evidence, extensions, git, limits, state
from orchestrator import plan as plan_mod
from orchestrator import policy as policy_mod
from orchestrator import reconcile as reconcile_mod
from orchestrator.debugger import DEFAULT_MAX_DEBUG_ATTEMPTS, run_debug_loop
from orchestrator.milestone import CriterionResult, GateResult, Verdict
from orchestrator.task_graph import Task, TaskGraph
from orchestrator.verifier import VerificationResult, overall_passed, run_verification
from orchestrator.workers.base import Worker

PLAN_PATH_REL = Path("docs") / "PLAN.md"

# Character budget for the repo-map portion of a per-task context block.
# Tunable per project via the `context_char_budget` policy (private layer).
DEFAULT_CONTEXT_CHAR_BUDGET = 2500


def plan_path(repo: Path) -> Path:
    return repo / PLAN_PATH_REL


def load_or_create_plan(
    repo: Path, project_name: str | None = None
) -> plan_mod.PlanDocument:
    p = plan_path(repo)
    if p.exists():
        return plan_mod.load(p)
    return plan_mod.new_plan(project_name or repo.name)


def _bullets_of(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")):
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
    _flag_undefined_criteria(doc)
    doc.save(plan_path(repo))
    state.save_task_store(repo, graph)
    extensions.run_hooks("reconcile_done", repo=repo, prompt=prompt_text, result=result)
    return IngestResult(plan=doc, graph=graph, reconcile_result=result)


_UNDEFINED_CRITERIA_BLOCKER = (
    "Milestone acceptance not defined: `## Acceptance Criteria` and/or "
    "`## Verification Commands` are empty, so `orchestrator verify` and the "
    "run verdict are task-status-only. Fill them in before treating a "
    "READY_FOR_REVIEW as real."
)


def _flag_undefined_criteria(doc: plan_mod.PlanDocument) -> None:
    """Record a one-time `## Blockers` line when the milestone has no
    acceptance criteria yet -- shaping a plan should not quietly leave the
    verdict meaningless."""
    missing = _plan_criteria_undefined(doc)
    body = doc.get_section("Blockers")
    if missing and "Milestone acceptance not defined" not in body:
        doc.append_to_section("Blockers", f"- {_UNDEFINED_CRITERIA_BLOCKER}")
    elif not missing and "Milestone acceptance not defined" in body:
        kept = "\n".join(
            ln
            for ln in body.splitlines()
            if "Milestone acceptance not defined" not in ln
        ).strip()
        doc.set_section("Blockers", kept or "None.")


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
    usage: dict = field(default_factory=dict)
    nothing_to_do: bool = False
    scoped: bool = False  # run was narrowed with only_task_ids
    session_limit_hint: str | None = None  # set when a worker hit a usage limit

    @property
    def run_status(self) -> str:
        """The run's own headline outcome, distinct from the milestone
        verdict. A scoped run (`--task`) that finished its selected tasks
        is `SCOPED_OK` even though the milestone as a whole is not
        `READY_FOR_REVIEW` -- the tasks it was asked to do succeeded."""
        if self.session_limit_hint is not None:
            return "BLOCKED_SESSION_LIMIT"
        if self.nothing_to_do:
            return "NO_WORK"
        if self.scoped:
            done = bool(self.task_outcomes) and all(
                o.status == "DONE" for o in self.task_outcomes
            )
            return "SCOPED_OK" if done else "BLOCKED"
        return self.verdict.result_status.value if self.verdict else "UNKNOWN"

    @property
    def ok(self) -> bool:
        """Whether the run met its own goal (for a CLI exit code)."""
        return self.run_status in ("READY_FOR_REVIEW", "SCOPED_OK", "NO_WORK")


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
    base_ref: str | None = None,
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
    wt = git.create_worktree(repo, run_id, task.id, base_ref=base_ref)
    task.assigned_worktree = str(wt.path)
    task.worker = implement_worker.name
    # Diffs are measured against the branch the work was based on -- the
    # WIP feature branch when --base was given, otherwise the default
    # branch. (The task branch is namespaced `orchestrator/<run>/<task>`
    # and create_worktree already refuses to operate on a protected one.)
    diff_base = base_ref or git.default_branch(repo)
    extensions.run_hooks("task_started", task=task, worker=implement_worker.name)

    response = implement_worker.implement(wt.path, task, context_block)
    evidence.save_worker_response(run_paths, task.id, "implement", response)

    commit = git.commit_all(
        wt.path, f"{task.id}: {task.title}\n\nImplemented by {implement_worker.name}."
    )
    evidence.save_diff(run_paths, task.id, git.diff(wt.path, base_ref=diff_base))
    extensions.run_hooks(
        "task_implemented",
        task=task,
        worker=implement_worker.name,
        response=response,
        commit=commit,
    )

    results = run_verification(
        task.verification,
        wt.path,
        timeout_per_command=verification_timeout,
        commit=commit,
        worker=implement_worker.name,
        attempt=1,
    )
    evidence.save_verification(run_paths, task.id, results)
    passed = overall_passed(results)
    extensions.run_hooks(
        "task_verified", task=task, results=results, passed=passed, attempt=1
    )

    debug_attempts = 0
    if not passed:
        outcome = run_debug_loop(
            cwd=wt.path,
            task=task,
            initial_results=results,
            verification_commands=task.verification,
            debugger_workers=debug_workers or [implement_worker],
            run_verification_fn=lambda: run_verification(
                task.verification,
                wt.path,
                timeout_per_command=verification_timeout,
                worker="debug",
            ),
            get_diff_fn=lambda: git.diff(wt.path, base_ref=diff_base),
            commit_fn=lambda msg: git.commit_all(wt.path, msg),
            max_attempts=max_debug_attempts,
            on_attempt=lambda record: extensions.run_hooks(
                "task_debug_attempt", task=task, record=record
            ),
        )
        for i, a in enumerate(outcome.attempts, start=1):
            evidence.save_worker_response(
                run_paths, task.id, f"debug-{i}", a.debugger_response
            )
            evidence.save_verification(run_paths, task.id, a.results_after)
        debug_attempts = len(outcome.attempts)
        results = outcome.final_results
        commit = git.head_commit(wt.path)
        evidence.save_diff(run_paths, task.id, git.diff(wt.path, base_ref=diff_base))
        if outcome.status != "FIXED":
            task.status = "BLOCKED"
            task.attempts += 1
            blocked_outcome = TaskOutcome(
                task_id=task.id,
                status="BLOCKED",
                worktree=wt.path,
                branch=wt.branch,
                commit=commit,
                verification=results,
                debug_attempts=debug_attempts,
                reason=outcome.reason,
            )
            extensions.run_hooks("task_blocked", task=task, outcome=blocked_outcome)
            return blocked_outcome

    task.status = "DONE"
    task.attempts += 1
    done_outcome = TaskOutcome(
        task_id=task.id,
        status="DONE",
        worktree=wt.path,
        branch=wt.branch,
        commit=commit,
        verification=results,
        debug_attempts=debug_attempts,
        reason="verification passed",
    )
    extensions.run_hooks("task_done", task=task, outcome=done_outcome)
    return done_outcome


def build_verdict(
    repo: Path,
    doc: plan_mod.PlanDocument,
    graph: TaskGraph,
    timeout_per_command: int = 600,
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
    ran: dict[str, bool] = {}
    if criteria_lines and len(criteria_lines) == len(verification_lines):
        for desc, cmd in zip(criteria_lines, verification_lines):
            r = run_verification([cmd], repo, timeout_per_command=timeout_per_command)[
                0
            ]
            ran[cmd] = r.passed
            verdict.criteria.append(
                CriterionResult(
                    description=desc, passed=r.passed, detail="" if r.passed else cmd
                )
            )
    else:
        for t in sorted(graph.all(), key=lambda t: t.id):
            if t.status == "DEFERRED":
                continue
            verdict.criteria.append(
                CriterionResult(
                    description=f"{t.id}: {t.title}", passed=t.status == "DONE"
                )
            )
        missing = _plan_criteria_undefined(doc)
        if missing:
            verdict.notes = (
                f"docs/PLAN.md has no bulleted `## {'` / `## '.join(missing)}` -- this "
                f"verdict reflects task DONE/BLOCKED status only, not milestone-level "
                f"acceptance. Fill those sections in for a real gate."
            )
        elif criteria_lines and verification_lines:
            verdict.notes = (
                f"`## Acceptance Criteria` ({len(criteria_lines)}) and "
                f"`## Verification Commands` ({len(verification_lines)}) are both non-empty "
                f"but different lengths -- they are matched positionally for the "
                f"requirements table, so it fell back to task status. Make the two lists "
                f"line up 1:1 to name each gate check."
            )

    # Milestone gate (ORCH-006): run every `## Verification Commands` entry
    # in the integration worktree. A gate failure blocks READY_FOR_REVIEW
    # even when every task is DONE. Commands already run above (1:1 case)
    # are reused, not re-run.
    for cmd in verification_lines:
        passed = ran.get(cmd)
        if passed is None:
            passed = run_verification(
                [cmd], repo, timeout_per_command=timeout_per_command
            )[0].passed
        verdict.gate.append(GateResult(command=cmd, passed=passed))

    return verdict


def _plan_criteria_undefined(doc: plan_mod.PlanDocument) -> list[str]:
    """Canonical sections a milestone needs before its verdict means
    anything, that are still empty / `_Not yet defined._`."""
    return [
        s
        for s in ("Acceptance Criteria", "Verification Commands")
        if not _bullets_of(doc.get_section(s))
    ]


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
    base_ref: str | None = None,
    only_task_ids: set[str] | None = None,
    resume_from: str | None = None,
) -> RunResult:
    """ingest + plan + execution + verification in one pass (spec section 16).

    `base_ref`: branch/ref every task worktree (and the integration
    worktree for the verdict) is created from. Defaults to the repo's
    detected default branch; pass a WIP feature branch to work tasks whose
    context only exists there. The protected branch is still never touched.

    `only_task_ids`: run just these task ids (and skip the rest of READY).
    A selected task whose dependency is not also selected is skipped with
    a BLOCKED-style note rather than run against an unmet dependency.

    `resume_from`: a prior run id under `.orchestrator/runs/`. Continues
    from the task store's current state (DONE tasks stay DONE), does NOT
    reconcile (`prompt_text` is ignored), and carries the prior run's
    `plan-before.md` forward. Use it after a `BLOCKED_SESSION_LIMIT` run.
    """
    if not implement_workers:
        raise ValueError("run() requires at least one implement worker")

    state.ensure_gitignore(repo)
    run_paths = state.init_run(repo)
    started_at = state.now_iso()

    prior_plan_before: Path | None = None
    if resume_from is not None:
        prior_root = state.orch_dir(repo) / "runs" / resume_from
        if not prior_root.is_dir():
            raise ValueError(f"no run {resume_from!r} under {prior_root.parent}")
        prompt_text = None  # resuming, not a new request -- do not reconcile
        pb = prior_root / "plan-before.md"
        if pb.is_file():
            prior_plan_before = pb

    doc = load_or_create_plan(repo)
    graph = state.load_task_store(repo)
    if prior_plan_before is not None:
        run_paths.plan_before.write_text(
            prior_plan_before.read_text(encoding="utf-8"), encoding="utf-8"
        )
    else:
        run_paths.plan_before.write_text(doc.render(), encoding="utf-8")

    ctx = context_mod.build_context(repo)
    project = doc.meta.project
    char_budget = policy_mod.effective_int(
        "context_char_budget", project, DEFAULT_CONTEXT_CHAR_BUDGET
    )
    run_wide_context = context_mod.with_providers(ctx, repo)

    session_limit: str | None = None
    if prompt_text:
        try:
            reconcile_result = reconcile_mod.reconcile(
                cwd=repo,
                prompt_text=prompt_text,
                plan=doc,
                graph=graph,
                context_block=run_wide_context,
                worker=implement_workers[0],
            )
        except reconcile_mod.ReconciliationError as e:
            hint = limits.session_limit_hint(str(e))
            if hint is None:
                raise
            session_limit = hint
            reconcile_result = None
        if (
            reconcile_result is not None
            and reconcile_result.worker_response is not None
        ):
            evidence.save_worker_response(
                run_paths, "reconcile", "reconcile", reconcile_result.worker_response
            )
            if session_limit is None:
                session_limit = limits.session_limit_hint(
                    reconcile_result.worker_response.raw_output,
                    reconcile_result.worker_response.summary,
                    reconcile_result.worker_response.error,
                )
        if reconcile_result is not None:
            extensions.run_hooks(
                "reconcile_done", repo=repo, prompt=prompt_text, result=reconcile_result
            )

    batches = graph.parallelizable_batches()
    if session_limit is not None:
        batches = []  # reconcile hit a usage limit -- do not start task work
    if only_task_ids is not None and session_limit is None:
        runnable = {t.id for b in batches for t in b}
        not_runnable = only_task_ids - runnable
        if not_runnable:
            raise ValueError(
                f"--task named {sorted(not_runnable)}, which is not runnable now "
                f"(runnable READY tasks: {sorted(runnable) or 'none'}). A task is not "
                f"runnable if it is not READY or if a dependency is still pending."
            )
        batches = [[t for t in batch if t.id in only_task_ids] for batch in batches]
        batches = [b for b in batches if b]
    ordered_tasks = [t for batch in batches for t in batch]
    assignment = _assign_workers(ordered_tasks, implement_workers)

    # ORCH-009: these pairs are serialised into different batches, but they
    # touch the same file, so their branches still collide at integration
    # -- surface that before doing the work.
    for a, b, path in graph.likely_overlaps(ordered_tasks):
        extensions.run_hooks("possible_overlap", task_a=a, task_b=b, path=path)

    extensions.run_hooks(
        "run_started",
        repo=repo,
        run_id=run_paths.run_id,
        prompt=prompt_text,
        task_ids=[t.id for t in ordered_tasks],
        batch_count=len(batches),
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
                    debug_workers=[
                        w for w in implement_workers if w is not assignment[task.id]
                    ]
                    + (debug_workers or []),
                    max_debug_attempts=max_debug_attempts,
                    verification_timeout=verification_timeout,
                    base_ref=base_ref,
                ): task
                for task in batch
            }
            for fut in as_completed(futures):
                outcomes.append(fut.result())

    outcomes.sort(key=lambda o: o.task_id)

    # A worker that blocked on a usage limit mid-run: detect it in the
    # failing verification output / the block reason so the run reports
    # BLOCKED_SESSION_LIMIT (resumable) rather than a plain BLOCKED.
    if session_limit is None:
        for o in outcomes:
            if o.status != "BLOCKED":
                continue
            texts = (
                [o.reason]
                + [r.stdout for r in o.verification]
                + [r.stderr for r in o.verification]
            )
            hint = limits.session_limit_hint(*texts)
            if hint is not None:
                session_limit = hint
                break

    state.save_task_store(repo, graph)
    doc.sync_task_section(graph)

    # "Nothing to do" is not a failure: reconcile ran, found the request
    # already satisfied (or a QUESTION/DEFER), and there were no pending
    # tasks either. Don't mark the milestone BLOCKED for that. A run cut
    # short by a usage limit is not "nothing to do".
    nothing_to_do = (
        session_limit is None
        and not ordered_tasks
        and not any(t.status not in ("DONE", "DEFERRED") for t in graph.all())
    )

    # Judge milestone acceptance against the combined result of this run's
    # completed work, not the untouched protected branch (nothing is merged
    # in v0 -- spec section 22 step 17 -- so the acceptance commands would
    # always fail if run in `repo` itself).
    done_branches = [o.branch for o in outcomes if o.status == "DONE" and o.branch]
    verify_root = repo
    integration_conflicts: list[str] = []
    if done_branches:
        try:
            integ = git.create_integration_worktree(
                repo, run_paths.run_id, done_branches, base_ref=base_ref
            )
            verify_root = integ.worktree.path
            integration_conflicts = integ.conflicted
        except git.GitError:
            verify_root = repo  # fall back to base-branch verification

    verdict = build_verdict(
        verify_root, doc, graph, timeout_per_command=verification_timeout
    )
    scoped = only_task_ids is not None
    notes: list[str] = [verdict.notes] if verdict.notes else []
    if integration_conflicts:
        notes.append(
            "merge conflicts integrating completed task branches "
            f"({', '.join(integration_conflicts)}) -- overlapping parallel work, "
            "verdict verification ran without them"
        )
    if scoped and outcomes:
        ran = ", ".join(o.task_id for o in outcomes)
        done = all(o.status == "DONE" for o in outcomes)
        remaining = sum(1 for t in graph.all() if t.status not in ("DONE", "DEFERRED"))
        notes.append(
            f"scoped run: executed {len(outcomes)} task(s) [{ran}] -- "
            f"{'all DONE' if done else 'NOT all DONE'}. The milestone verdict below "
            f"still counts {remaining} task(s) outside this run's scope."
        )
    if notes:
        verdict.notes = "  ".join(notes)
    # A scoped run does not decide the milestone status: it only ran part
    # of it. Leave doc.meta.status alone unless this was a full run.
    if not nothing_to_do and not scoped:
        doc.meta.status = verdict.result_status
    doc.save(plan_path(repo))
    run_paths.plan_after.write_text(doc.render(), encoding="utf-8")

    usage_summary = evidence.run_usage_summary(run_paths)
    (run_paths.root / "usage.json").write_text(
        json.dumps(usage_summary, indent=2) + "\n", encoding="utf-8"
    )
    verdict_text = verdict.render() + "\n" + evidence.format_cost_section(usage_summary)
    if nothing_to_do:
        verdict_text = verdict_text.replace(
            f"NOT READY FOR {verdict.target_version}",
            "NO WORK -- request already satisfied or no pending tasks",
        )
    if session_limit is not None:
        reset = "an unknown time" if session_limit == "unknown" else session_limit
        verdict_text = verdict_text.replace(
            f"NOT READY FOR {verdict.target_version}",
            f"PAUSED -- an agent hit its session/usage limit (resets {reset}). "
            f"Completed tasks are saved; re-run to resume.",
        )
    evidence.write_verdict(run_paths, verdict_text)

    result = RunResult(
        manifest=None,
        run_paths=run_paths,
        plan=doc,
        graph=graph,  # type: ignore[arg-type]
        task_outcomes=outcomes,
        verdict=verdict,
        usage=usage_summary,
        nothing_to_do=nothing_to_do,
        scoped=scoped,
        session_limit_hint=session_limit,
    )

    manifest_notes = "reconcile found nothing to do" if nothing_to_do else ""
    if session_limit is not None:
        manifest_notes = f"paused: agent session/usage limit (resets {session_limit})"
    if resume_from is not None:
        manifest_notes = (
            manifest_notes + "  " if manifest_notes else ""
        ) + f"resumed from run {resume_from}"
    manifest = state.RunManifest(
        run_id=run_paths.run_id,
        repo=str(repo),
        prompt=prompt_text or "",
        started_at=started_at,
        protected_branch=git.default_branch(repo),
        finished_at=state.now_iso(),
        status=result.run_status,
        active_milestone=doc.meta.active_milestone,
        task_ids=[o.task_id for o in outcomes],
        notes=manifest_notes,
        resumed_from=resume_from,
    )
    manifest.save(run_paths)
    result.manifest = manifest
    extensions.run_hooks(
        "run_finished", manifest=manifest, verdict=verdict, run_paths=run_paths
    )

    return result


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
