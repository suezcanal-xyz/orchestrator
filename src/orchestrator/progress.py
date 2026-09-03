"""Console live-progress printer, built entirely on the public hook API
(`extensions.register_hook`) -- proof that a private/other integration
(a Slack notifier, a desktop notification, a real dashboard) could do the
exact same thing without touching `engine.py`.

Without this, `orchestrator run` is silent until it returns, which for a
multi-minute run with real Codex/Claude calls reads as hung. `cli.py`
calls `register_console_progress()` before `engine.run()` for interactive
use; a caller that wants only the final summary (e.g. a script consuming
`engine.run()` as a library) simply doesn't call it.
"""

from __future__ import annotations

import sys
import threading

from orchestrator import extensions

_lock = threading.Lock()


def _p(line: str) -> None:
    with _lock:
        print(line, file=sys.stdout, flush=True)


def _on_run_started(**kw) -> None:
    task_ids = kw.get("task_ids") or []
    _p(f"[{kw.get('run_id')}] {len(task_ids)} task(s), {kw.get('batch_count')} batch(es): {', '.join(task_ids) or '(none)'}")


def _on_reconcile_done(**kw) -> None:
    result = kw["result"]
    added = ", ".join(result.added_task_ids) or "none"
    _p(f"[reconcile] {result.classification} -- added: {added}")


def _on_task_started(**kw) -> None:
    task = kw["task"]
    _p(f"  {task.id}: {kw['worker']} implementing '{task.title}'...")


def _on_task_implemented(**kw) -> None:
    task, response = kw["task"], kw["response"]
    _p(f"  {task.id}: {kw['worker']} done implementing ({response.duration_seconds:.1f}s)")


def _on_task_verified(**kw) -> None:
    task, results = kw["task"], kw["results"]
    status = "PASS" if kw["passed"] else "FAIL"
    _p(f"  {task.id}: verification {status} ({len(results)} command(s), attempt {kw['attempt']})")


def _on_task_debug_attempt(**kw) -> None:
    task, record = kw["task"], kw["record"]
    outcome = "fixed" if record.passed else "still failing"
    _p(f"  {task.id}: debug attempt {record.attempt} by {record.debugger_worker} ({record.classification}) -> {outcome}")


def _on_task_done(**kw) -> None:
    _p(f"  {kw['task'].id}: DONE")


def _on_task_blocked(**kw) -> None:
    outcome = kw["outcome"]
    _p(f"  {kw['task'].id}: BLOCKED -- {outcome.reason}")


def _on_run_finished(**kw) -> None:
    manifest = kw["manifest"]
    _p(f"[{manifest.run_id}] finished: {manifest.status}")


def _on_possible_overlap(**kw) -> None:
    _p(f"  possible overlap: {kw['task_a']} and {kw['task_b']} both touch {kw['path']} "
       f"-- serialised, but their branches will conflict at integration")


_HANDLERS = {
    "run_started": _on_run_started,
    "possible_overlap": _on_possible_overlap,
    "reconcile_done": _on_reconcile_done,
    "task_started": _on_task_started,
    "task_implemented": _on_task_implemented,
    "task_verified": _on_task_verified,
    "task_debug_attempt": _on_task_debug_attempt,
    "task_done": _on_task_done,
    "task_blocked": _on_task_blocked,
    "run_finished": _on_run_finished,
}

_registered = False


def register_console_progress() -> None:
    """Idempotent: safe to call more than once (e.g. across CLI invocations
    in the same process, as in tests) without printing duplicate lines."""
    global _registered
    if _registered:
        return
    for event, handler in _HANDLERS.items():
        extensions.register_hook(event, handler)
    _registered = True
