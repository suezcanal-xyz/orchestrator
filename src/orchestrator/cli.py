"""CLI v0 (spec section 16).

    orchestrator inspect <repo>
    orchestrator ingest <repo> "<prompt>"
    orchestrator plan <repo>
    orchestrator run <repo> [--prompt "<current request>"]
    orchestrator verify <repo>
    orchestrator status <repo>

Concrete workers (Codex, Claude) are wired here, at the edge -- everything
below `engine.py` only knows about the abstract Worker interface, so a
private extension can register additional workers via
`orchestrator.extensions.register_worker` and pass `--worker <name>`
without this module changing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from orchestrator import engine, extensions
from orchestrator.debugger import DEFAULT_MAX_DEBUG_ATTEMPTS
from orchestrator.workers.base import Worker


def _builtin_workers() -> dict[str, type[Worker]]:
    from orchestrator.workers.claude import ClaudeWorker
    from orchestrator.workers.codex import CodexWorker

    return {"codex": CodexWorker, "claude": ClaudeWorker}


def _resolve_workers(names: tuple[str, ...]) -> list[Worker]:
    builtin = _builtin_workers()
    registered = extensions.registered_workers()
    out: list[Worker] = []
    for name in names:
        if name in registered:
            out.append(registered[name]())
        elif name in builtin:
            out.append(builtin[name]())
        else:
            available = sorted(set(builtin) | set(registered))
            raise click.ClickException(f"unknown worker {name!r}; available: {available}")
    return out


@click.group()
@click.version_option(package_name="orchestrator")
def main() -> None:
    """Milestone-driven multi-agent development control plane."""


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
def inspect(repo: Path) -> None:
    """Build and print the lightweight repository context map (no edits)."""
    ctx = engine.inspect(repo)
    click.echo(ctx.to_prompt_block(max_chars=8000))


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("prompt")
@click.option("--worker", default="claude", help="Worker to use for reconciliation.")
def ingest(repo: Path, prompt: str, worker: str) -> None:
    """Reconcile a new human prompt into docs/PLAN.md and the task store."""
    workers = _resolve_workers((worker,))
    result = engine.ingest(repo, prompt, workers[0])
    rr = result.reconcile_result
    click.echo(f"classification: {rr.classification}")
    if rr.added_task_ids:
        click.echo(f"added tasks: {', '.join(rr.added_task_ids)}")
    if rr.skipped_duplicates:
        click.echo(f"already tracked (skipped): {', '.join(rr.skipped_duplicates)}")
    click.echo(f"docs/PLAN.md updated: {engine.plan_path(repo)}")


@main.command(name="plan")
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
def plan_cmd(repo: Path) -> None:
    """Print the current docs/PLAN.md (read-only)."""
    p = engine.plan_path(repo)
    if not p.exists():
        raise click.ClickException(f"{p} does not exist yet -- run `orchestrator ingest` first")
    click.echo(p.read_text(encoding="utf-8"))


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--prompt", default=None, help="Current request; omit to just execute existing READY tasks.")
@click.option("--worker", "workers", multiple=True, default=("claude", "codex"), help="Implement workers, in assignment order.")
@click.option("--max-debug-attempts", default=DEFAULT_MAX_DEBUG_ATTEMPTS, show_default=True)
@click.option("--verification-timeout", default=600, show_default=True, help="Seconds per verification command.")
def run(repo: Path, prompt: str | None, workers: tuple[str, ...], max_debug_attempts: int, verification_timeout: int) -> None:
    """ingest + plan + execution + verification in one pass (the daily entry point)."""
    resolved = _resolve_workers(workers)
    result = engine.run(
        repo=repo, prompt_text=prompt, implement_workers=resolved,
        max_debug_attempts=max_debug_attempts, verification_timeout=verification_timeout,
    )
    for o in result.task_outcomes:
        click.echo(f"{o.task_id}: {o.status}  (debug attempts: {o.debug_attempts})")
    click.echo("")
    click.echo(result.verdict.render())
    click.echo(f"run: {result.run_paths.root}")
    if result.verdict.result_status.value != "READY_FOR_REVIEW":
        sys.exit(1)


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--verification-timeout", default=600, show_default=True)
def verify(repo: Path, verification_timeout: int) -> None:
    """Run milestone-level acceptance criteria against the current repo state, no task execution."""
    doc = engine.load_or_create_plan(repo)
    from orchestrator import state as state_mod

    graph = state_mod.load_task_store(repo)
    verdict = engine.build_verdict(repo, doc, graph, timeout_per_command=verification_timeout)
    click.echo(verdict.render())
    if not verdict.ready:
        sys.exit(1)


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON instead of text.")
def status(repo: Path, as_json: bool) -> None:
    """Summarize project/version/milestone/task counts. No execution."""
    s = engine.status(repo)
    if as_json:
        click.echo(json.dumps(s, indent=2))
        return
    click.echo(f"project:          {s['project']}")
    click.echo(f"current_version:  {s['current_version']}")
    click.echo(f"target_version:   {s['target_version']}")
    click.echo(f"active_milestone: {s['active_milestone']}")
    click.echo(f"status:           {s['status']}")
    click.echo(f"tasks:            {s['total_tasks']} total")
    for k, v in sorted(s["tasks_by_status"].items()):
        click.echo(f"  {k}: {v}")


if __name__ == "__main__":
    main()
