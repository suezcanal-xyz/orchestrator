"""Automated debugging loop (spec section 12).

This is a primary feature, not an optional extra. On a verification
failure: collect evidence, classify it, generate a debug task, attempt a
targeted fix, rerun verification, and repeat up to max_debug_attempts
before giving up and reporting BLOCKED with the exact reason -- never
hiding an unsuccessful attempt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from orchestrator.verifier import VerificationResult, failing, overall_passed

if TYPE_CHECKING:
    from orchestrator.task_graph import Task
    from orchestrator.workers.base import Worker, WorkerResponse

DEFAULT_MAX_DEBUG_ATTEMPTS = 3

_CLASSIFIERS: list[tuple[str, str]] = [
    (
        r"ModuleNotFoundError|ImportError|Cannot find module",
        "MISSING_DEPENDENCY_OR_IMPORT",
    ),
    (r"AssertionError|expect\(.*\)\.to", "ASSERTION_FAILURE"),
    (r"SyntaxError|Unexpected token|ParseError", "SYNTAX_ERROR"),
    (r"TypeError", "TYPE_ERROR"),
    (r"TimeoutError|timed out", "TIMEOUT"),
    (r"ConnectionError|ECONNREFUSED|connection refused", "CONNECTIVITY"),
    (r"PermissionError|EACCES|Access is denied", "PERMISSION"),
    (r"FileNotFoundError|ENOENT|No such file", "MISSING_FILE"),
]


def classify_failure(results: list[VerificationResult]) -> str:
    import re

    blob = "\n".join(r.stderr + "\n" + r.stdout for r in failing(results))
    for pattern, label in _CLASSIFIERS:
        if re.search(pattern, blob, re.IGNORECASE):
            return label
    return "UNKNOWN_FAILURE"


@dataclass
class DebugAttemptRecord:
    attempt: int
    classification: str
    debugger_worker: str
    debugger_response: WorkerResponse
    commit: str | None
    results_after: list[VerificationResult]
    passed: bool


@dataclass
class DebugOutcome:
    status: str  # "FIXED" | "BLOCKED"
    attempts: list[DebugAttemptRecord] = field(default_factory=list)
    final_results: list[VerificationResult] = field(default_factory=list)
    reason: str = ""


def build_evidence_block(
    task: Task,
    results: list[VerificationResult],
    diff_text: str,
    previous_attempts: list[DebugAttemptRecord],
    max_diff_chars: int = 4000,
) -> str:
    lines = [
        f"Original requirement: {task.title}",
        "Expected (acceptance criteria):",
        *[f"  - {a}" for a in task.acceptance],
        "",
        "Observed: verification failed.",
        "",
    ]
    for r in failing(results):
        lines += [
            f"Failing command: {r.command}  (exit {r.exit_code}, attempt {r.attempt})",
            "stdout (tail):",
            r.stdout[-1500:],
            "stderr (tail):",
            r.stderr[-1500:],
            "",
        ]
    lines += ["Current diff (tail):", "```diff", diff_text[-max_diff_chars:], "```", ""]
    if previous_attempts:
        lines.append("Previous debug attempts on this task:")
        for a in previous_attempts:
            lines.append(
                f"  attempt {a.attempt} ({a.classification}, worker={a.debugger_worker}): "
                f"{'passed' if a.passed else 'still failing'} -- {a.debugger_response.summary[:300]}"
            )
    return "\n".join(lines)


def run_debug_loop(
    *,
    cwd: Path,
    task: Task,
    initial_results: list[VerificationResult],
    verification_commands: list[str],
    debugger_workers: list[Worker],
    run_verification_fn: Callable[[], list[VerificationResult]],
    get_diff_fn: Callable[[], str],
    commit_fn: Callable[[str], str | None],
    max_attempts: int = DEFAULT_MAX_DEBUG_ATTEMPTS,
    on_attempt: Callable[[DebugAttemptRecord], None] | None = None,
) -> DebugOutcome:
    """Fail -> evidence -> classify -> targeted fix -> rerun -> repeat.

    debugger_workers is consulted round-robin across attempts, which is how
    cross-model debugging (spec section 12: Codex implements, verification
    fails, Claude diagnoses, Codex applies the correction, or the inverse)
    falls out naturally: pass e.g. [claude_worker, codex_worker] and attempt
    1 uses claude, attempt 2 uses codex, attempt 3 uses claude again.

    on_attempt, if given, is called synchronously right after each attempt
    finishes (pass/fail already known) -- this is how a caller gets live
    progress out of a loop that can otherwise run silently for minutes.
    """
    results = initial_results
    attempts: list[DebugAttemptRecord] = []

    if overall_passed(results):
        return DebugOutcome(
            status="FIXED",
            attempts=[],
            final_results=results,
            reason="no failure to debug",
        )

    if not debugger_workers:
        return DebugOutcome(
            status="BLOCKED",
            attempts=[],
            final_results=results,
            reason="no debugger workers configured",
        )

    for attempt_n in range(1, max_attempts + 1):
        classification = classify_failure(results)
        worker = debugger_workers[(attempt_n - 1) % len(debugger_workers)]
        evidence = build_evidence_block(task, results, get_diff_fn(), attempts)

        response = worker.debug(cwd, task, evidence)
        commit = commit_fn(
            f"{task.id}: debug attempt {attempt_n} ({worker.name}, {classification})"
        )

        results = run_verification_fn()
        passed = overall_passed(results)

        record = DebugAttemptRecord(
            attempt=attempt_n,
            classification=classification,
            debugger_worker=worker.name,
            debugger_response=response,
            commit=commit,
            results_after=results,
            passed=passed,
        )
        attempts.append(record)
        if on_attempt:
            on_attempt(record)

        if passed:
            return DebugOutcome(
                status="FIXED",
                attempts=attempts,
                final_results=results,
                reason="verification passed",
            )

    last = attempts[-1]
    reason = (
        f"exhausted {max_attempts} debug attempts; last classification={last.classification}, "
        f"still failing: {[r.command for r in failing(results)]}"
    )
    return DebugOutcome(
        status="BLOCKED", attempts=attempts, final_results=results, reason=reason
    )
