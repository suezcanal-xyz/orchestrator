"""Effective run configuration: default < registered private policy < explicit CLI flag.

`orchestrator-private` registers policy functions via
`orchestrator.extensions.register_policy` (worker lists per project/stage,
`max_debug_attempts`, `verification_timeout_seconds`, `context_char_budget`,
...). Nothing consumed them before v0.2.0 -- the CLI passed its own flag
defaults straight through to `engine.run`, so a private config file had no
effect on a run.

This module is the single, deterministic place that layers the three
sources. It is pure bookkeeping (spec section 23): no model calls, no I/O
beyond calling already-registered functions.

Precedence, highest first:
  1. an explicit value the user passed on the CLI
  2. a policy function registered by a private extension, if any
  3. the built-in default
"""

from __future__ import annotations

from orchestrator import extensions

# CLI-level default worker order when neither a flag nor a policy applies.
DEFAULT_IMPLEMENT_WORKERS: tuple[str, ...] = ("claude", "codex")


def effective_workers(
    project: str | None,
    cli_workers: tuple[str, ...] | None,
    *,
    stage: str = "implement",
) -> list[str]:
    """Resolve the ordered worker list for `project` at `stage`.

    `cli_workers` is whatever `--worker` produced: a non-empty tuple means
    the user chose explicitly and wins outright; an empty tuple or None
    means "not specified", so a registered `workers` policy is consulted,
    then the built-in default.
    """
    if cli_workers:
        return list(cli_workers)

    policy = extensions.get_policy("workers")
    if policy is not None:
        try:
            resolved = policy(project, stage)
        except TypeError:
            # tolerate a one-arg policy (project only)
            resolved = policy(project)
        if resolved:
            return list(resolved)

    return list(DEFAULT_IMPLEMENT_WORKERS)


def effective_int(
    name: str,
    project: str | None,
    default: int,
    cli_value: int | None = None,
) -> int:
    """Resolve an integer policy (`max_debug_attempts`,
    `verification_timeout_seconds`, `context_char_budget`, ...)."""
    if cli_value is not None:
        return cli_value

    policy = extensions.get_policy(name)
    if policy is not None:
        try:
            resolved = policy(project)
        except TypeError:
            resolved = policy(project, name)
        if resolved is not None:
            return int(resolved)

    return default
