"""Extension points for orchestrator-private (spec section 5).

Five narrow registries, nothing cleverer. Project- or organization-specific
capability -- private prompts, policies, extra verification commands,
context providers, alternate workers -- registers here without touching
this repository. No plugin discovery, no entry-point scanning in v0
(spec section 21: avoid overengineering).
"""

from __future__ import annotations

from typing import Any, Callable

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
    for fn in _hooks.get(event, []):
        fn(*args, **kwargs)


def reset_extensions() -> None:
    """Test/debug helper: clear every registry."""
    _workers.clear()
    _verifiers.clear()
    _context_providers.clear()
    _policies.clear()
    _hooks.clear()
