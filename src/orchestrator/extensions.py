"""Extension points for orchestrator-private (spec section 5).

Five narrow registries, nothing cleverer. Project- or organization-specific
capability -- private prompts, policies, extra verification commands,
context providers, alternate workers -- registers here without touching
this repository. No plugin discovery, no entry-point scanning in v0
(spec section 21: avoid overengineering).

Hooks (register_hook / run_hooks) are how a caller gets live progress out
of `engine.run()`, which otherwise runs silently until it returns. Events
fired by engine.py, in order, with the keyword arguments each call
receives:

    reconcile_done(repo, prompt, result: ReconcileResult)
    run_started(repo, run_id, prompt, task_ids, batch_count)
    task_started(task, worker)
    task_implemented(task, worker, response, commit)
    task_verified(task, results, passed, attempt)
    task_debug_attempt(task, record: DebugAttemptRecord)      -- zero or more times
    task_done(task, outcome) | task_blocked(task, outcome)    -- exactly one
    run_finished(manifest, verdict, run_paths)

`task_*` events can fire from multiple worker threads concurrently (tasks
in the same parallel batch run on separate threads) -- a hook that isn't
naturally thread-safe (e.g. writing to a shared file) must lock itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

WorkerFactory = Callable[[], Any]
VerifierFn = Callable[..., Any]
ContextProviderFn = Callable[[Any], dict]
PolicyFn = Callable[..., Any]
HookFn = Callable[..., None]

_workers: dict[str, WorkerFactory] = {}
_verifiers: dict[str, VerifierFn] = {}
_context_providers: list[ContextProviderFn] = []
_policies: dict[str, PolicyFn] = {}
_hooks: dict[str, list[HookFn]] = {}


def register_worker(name: str, factory: WorkerFactory) -> None:
    _workers[name] = factory


def get_worker(name: str) -> WorkerFactory | None:
    return _workers.get(name)


def registered_workers() -> dict[str, WorkerFactory]:
    return dict(_workers)


def register_verifier(name: str, fn: VerifierFn) -> None:
    _verifiers[name] = fn


def get_verifier(name: str) -> VerifierFn | None:
    return _verifiers.get(name)


def register_context_provider(fn: ContextProviderFn) -> None:
    _context_providers.append(fn)


def context_providers() -> list[ContextProviderFn]:
    return list(_context_providers)


def register_policy(name: str, fn: PolicyFn) -> None:
    _policies[name] = fn


def get_policy(name: str, default: PolicyFn | None = None) -> PolicyFn | None:
    return _policies.get(name, default)


def register_hook(event: str, fn: HookFn) -> None:
    _hooks.setdefault(event, []).append(fn)


def run_hooks(event: str, *args: Any, **kwargs: Any) -> None:
    """Call every hook registered for `event`, in registration order.

    A hook raising never breaks the pipeline calling it (hooks are for
    progress reporting / notifications, not control flow) -- the exception
    is printed to stderr and the remaining hooks still run.
    """
    for fn in _hooks.get(event, []):
        try:
            fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            import sys

            print(
                f"[orchestrator] hook {fn!r} for event {event!r} raised: {e!r}",
                file=sys.stderr,
            )


def reset_extensions() -> None:
    """Test/debug helper: clear every registry."""
    _workers.clear()
    _verifiers.clear()
    _context_providers.clear()
    _policies.clear()
    _hooks.clear()
