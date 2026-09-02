# Development

## Setup

```bash
pip install -e ".[dev]"
python -m pytest -q
```

Requires Python 3.11+, `git` on PATH, and (only for the live worker paths)
`codex` and `claude` CLIs authenticated and on PATH.

## Layout

See `docs/ARCHITECTURE.md` for the module map. Short version: `plan.py` /
`milestone.py` / `task_graph.py` are the data model, `git.py` /
`verifier.py` are deterministic infrastructure, `workers/` is the only
place that shells out to a model, `reconcile.py` / `debugger.py` /
`engine.py` are the orchestration logic that ties them together, and
`cli.py` is the thin edge that wires concrete workers into it.

## Methodology (spec section 23)

Build incrementally: inspect existing code and tests first, write a
failing test, implement the smallest thing that passes it, run the full
suite, commit, move on. Every module added to this repository so far
followed that loop -- see the git history.

**Prefer deterministic code over a model call.** A model call is for
reasoning: classifying a prompt against a plan (`reconcile.py`),
implementing a task, diagnosing a failure. State transitions, dependency
resolution, parsing, verification, retries, and git operations are plain
Python with no model in the loop, and are unit-tested without mocking an
LLM. If you're about to add a model call, first ask whether the thing you
want it to decide could instead be computed from data that's already
structured (a task's `status`, a verification exit code, a file-overlap
check) -- if so, it should be.

**A worker's own claim of success has zero authority anywhere in this
codebase.** If you're adding a new code path that trusts a
`WorkerResponse.summary` as proof something happened, it's very likely
wrong -- route through `verifier.run_verification` instead, or make the
thing checkable and check it deterministically.

## Testing conventions

- Every module has a matching `tests/test_<module>.py`. Deterministic
  modules (`plan`, `task_graph`, `git`, `context`, `verifier`, `state`,
  `evidence`, `reconcile`, `debugger`) are tested directly with no worker
  involved.
- Modules that need a `Worker` (`reconcile.py`, `debugger.py`,
  `engine.py`) are tested against a small scripted fake (see
  `ScriptedWorker` in `tests/test_engine.py`, `FakeWorker` in
  `tests/test_debugger.py`) that implements `Worker._invoke()` in plain
  Python -- no CLI, no network, no cost, deterministic. This is what
  `python -m pytest` runs by default and what CI should run.
- A real end-to-end run against the actual `codex` / `claude` CLIs is a
  separate, explicitly-invoked scenario (not part of the default test
  suite, since it costs real money and depends on external services being
  reachable and authenticated) -- see `examples/demo-repo/` and the v0.1.0
  closed-loop scenario in spec section 22.
- Git-backed tests create a throwaway repo per test via the `init_repo`
  helper in `tests/conftest.py` (a `tmp_path` fixture, never the real
  `orchestrator` repo itself).

## Adding a worker

Implement `Worker._invoke()` (see `workers/codex.py` / `workers/claude.py`
for the shape) and either add it to `cli._builtin_workers()` (public,
generally useful) or register it from a private extension:

```python
from orchestrator import extensions
extensions.register_worker("my-model", MyWorker)
```

then pass `--worker my-model` on the CLI. No other file needs to change --
`engine.py` and `reconcile.py`/`debugger.py` only depend on the abstract
`Worker` interface. `orchestrator doctor` reports any agent CLI it finds
on PATH with no registered Worker, so you know what's worth adding.

**opencode** (detected by `orchestrator doctor`, not yet implemented):
`opencode run [message] --dir <path> --format json --auto` is the
non-interactive contract (verified via `opencode run --help`; `--auto`
auto-approves permissions, the same class of flag as Codex's
`danger-full-access` or Claude's `bypassPermissions` -- same caveats
apply, see `docs/SECURITY.md`). This has **not** been live-verified end
to end in this repo (no authenticated provider was available while
building it) -- confirm the JSON output shape (`--format json`) actually
matches what `WorkerResponse` expects before trusting it in production.

## Adding a verifier, context provider, policy, or hook

Same pattern, via the other four functions in `extensions.py`. See
`docs/ARCHITECTURE.md` "Extension points" for an example of each.

## Style

- Type hints on every public function; `from __future__ import annotations`
  at the top of every module.
- Dataclasses for structured records, not dicts passed around by
  convention.
- No abstraction added ahead of a second concrete use (spec section 21) --
  if you're building a plugin system, a registry, or a config layer that
  nothing yet needs, stop and cut it.

## CI

`.github/workflows/ci.yml` runs the mocked test suite (never the live
integration test -- that costs real API usage and needs authenticated
CLIs, neither appropriate for a public CI run) on `ubuntu-latest` and
`windows-latest`, across Python 3.11 and 3.12, on every push to `main` and
every PR. Keep it that way: this repo shells out to OS-specific process
invocation (see `workers/base.py:resolve_executable` and its
`shell=True`-on-Windows-`.cmd`-shims history) -- Windows-only bugs have
already slipped through once by only testing on the author's own machine.
It also runs `python -m build` to catch packaging breakage early.

## Releasing

The PyPI distribution name is `suez-orchestrator` (`orchestrator` itself
is already taken); the import package and CLI command stay `orchestrator`
either way -- `pip install suez-orchestrator` gives you `import
orchestrator` and the `orchestrator` command, unchanged.

One-time setup on PyPI, before the first release:

1. Create the project on PyPI (upload once by hand with `twine`, or use
   PyPI's "create a new pending publisher" flow, which reserves the name
   without an upload).
2. Under the project's Publishing settings, add a Trusted Publisher:
   GitHub, owner `suezcanal-xyz`, repository `orchestrator`, workflow
   `publish.yml`, environment `pypi`.
3. In the GitHub repo settings, create an environment named `pypi`
   (Settings -> Environments) -- `publish.yml` deploys through it.

Once that's done, every release is just:

```bash
# bump version in pyproject.toml, commit it, then:
git tag v0.1.1
git push origin v0.1.1
```

`.github/workflows/publish.yml` builds the sdist/wheel and publishes via
OIDC (no stored PyPI token). Note: the GitHub repository is currently
**private**; PyPI itself doesn't require a public source repo to accept an
upload, but a private repo means `project.urls.Repository` in
`pyproject.toml` 404s for anyone without access -- make the repo public
(or drop/adjust that URL) before treating this as a real public release.
