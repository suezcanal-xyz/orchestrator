# Architecture

## Central object

The central object is not the agent. It is the target project's
`docs/PLAN.md` (spec section 1, 3; format documented in `PLAN-SPEC.md`).
Everything else in this repository exists to read it, update it, turn it
into a task graph, execute that graph, verify the result, and write it
back.

```text
CURRENT USER PROMPT
        v
CURRENT REPOSITORY STATE
        v
CURRENT PLAN.md
        v
   RECONCILE            (reconcile.py, one model call, deterministic merge)
        v
UPDATED PLAN.md -> TASK GRAPH        (plan.py, task_graph.py)
        v
   EXECUTION            (engine.py: worktree per task, worker per task)
        v
   VERIFICATION         (verifier.py: run declared commands, nothing else counts)
        v
   DEBUG                (debugger.py: evidence -> fix -> reverify, up to 3x)
        v
UPDATED PLAN.md + VERDICT.md
        v
NEXT ITERATION
```

## Module map

```text
src/orchestrator/
  plan.py         docs/PLAN.md parser/writer -- frontmatter + fixed sections,
                  round-trips unknown content, regenerates ## Tasks from the
                  TaskGraph.
  milestone.py    ProjectMeta / MilestoneStatus / Verdict -- the small,
                  typed structures around version and completion status.
  task_graph.py   Task + TaskGraph: structured task records (JSON, not
                  prose), dependency DAG, cycle detection, file-overlap
                  based batching for safe parallel execution.
  context.py      Lightweight repo inspection: README/AGENTS.md/CLAUDE.md,
                  manifests, CI config, test/migration dirs, TODO/FIXME
                  markers, advisory CURRENT/LEGACY/UNKNOWN/DEPRECATED/
                  GENERATED/VENDOR classification. Produces task-specific
                  context blocks, never a full-repo dump.
  git.py          Worktree isolation: orchestrator/<run>/<task> branches,
                  diff/commit/status helpers, a protected-branch guard.
                  Pure git-CLI wrapping, no model calls.
  workers/
    base.py       Worker ABC + the four semantic operations (inspect,
                  implement, review, debug) plus propose_tasks, all built
                  from one shared prompt-construction layer so a new CLI
                  worker only has to implement `_invoke()`.
    codex.py      OpenAI Codex CLI worker (`codex exec`).
    claude.py     Anthropic Claude Code CLI worker (`claude -p`).
    opencode.py   opencode CLI worker (`opencode run --format json`).
  verifier.py     Runs declared verification commands, captures full
                  evidence (exit code, stdout/stderr, duration, commit).
                  A worker's claim of success has zero authority here.
  debugger.py     Fail -> classify -> evidence -> targeted fix -> reverify
                  loop, bounded by max_debug_attempts (default 3), supports
                  cross-model debugging by round-robining debugger_workers.
  reconcile.py    The plan-reconciliation algorithm (spec section 18):
                  classifies a new prompt against the current plan and
                  repository reality via one worker call, then merges the
                  result deterministically (dedup by title, ID assignment,
                  Change History entry).
  state.py        Run bootstrap: `.orchestrator/state/tasks.json` (durable,
                  cross-run) and `.orchestrator/runs/<run-id>/` (one
                  immutable folder per run). Ensures `.orchestrator/` is
                  gitignored in the target repo.
  evidence.py     Serializes worker responses, diffs, verification results
                  and the final verdict into a run's evidence tree.
  engine.py       Ties it all together: ingest / run / status. Runs each
                  batch of independent tasks concurrently via a thread
                  pool (safe because each task is fully isolated in its
                  own worktree and the actual work happens in subprocess
                  calls).
  extensions.py   Five registries (register_worker / register_verifier /
                  register_context_provider / register_policy /
                  register_hook) -- the only way orchestrator-private is
                  meant to extend this repository's behavior.
  policy.py       Resolves effective run config by layering built-in
                  default < registered private policy < explicit CLI flag
                  (worker list, max_debug_attempts, verification_timeout,
                  context_char_budget). Deterministic, no model calls.
  scaffold.py     `orchestrator init`: drop a starter docs/PLAN.md +
                  AGENTS.md into a repo (packaged templates/), never
                  overwriting.
  dashboard/      Optional (`dashboard` extra): FastAPI app + one static
                  HTML page behind `orchestrator onboarding`. A thin shell
                  over doctor / init / run, progress streamed off the hook
                  bus. No auth; 127.0.0.1 only.
  cli.py          `orchestrator inspect|init|ingest|plan|run|verify|status|
                  doctor|onboarding`. The only place concrete workers
                  (Codex, Claude, opencode) are imported by name;
                  everything below only knows the abstract Worker interface.
```

## Execution model

One task = one git worktree = one branch named
`orchestrator/<run-id>/<task-id>`, branched from the repository's detected
default branch and never merged back automatically (spec section 17).
`TaskGraph.parallelizable_batches()` groups ready tasks so that two tasks
run in the same batch only if their declared `files_hint` provably don't
overlap; a task with no `files_hint` is scheduled alone, conservatively.
Within a batch, `engine.run()` executes tasks concurrently with a thread
pool -- each task's actual work happens in a `subprocess.run()` call to a
CLI worker, which releases the GIL while it runs, so this is genuine
concurrent Codex/Claude execution, not a mechanism that exists but goes
unused.

After a worker call returns, the **orchestrator** -- not the worker --
performs the git commit (`git.commit_all`), so there is always a known,
deterministic commit to attach evidence to regardless of what the model
did or didn't commit itself.

## Extension points

`orchestrator-private` (or any other private extension repo) registers
capability through `orchestrator.extensions` at process start, before
calling into `engine`/`cli`:

```python
from orchestrator import extensions
from my_private_pkg.workers import GeminiWorker

extensions.register_worker("gemini", GeminiWorker)
extensions.register_context_provider(my_extra_context_fn)
extensions.register_policy("max_debug_attempts", lambda project: 5 if project == "seacommons" else 3)
extensions.register_hook("after_task", notify_slack)
```

Nothing in `orchestrator` imports from `orchestrator-private`; the
dependency runs one way only (spec section 4).

## What v0 deliberately excludes, and why

Per spec section 21, added only when a real need shows up, not
speculatively:

- **Web UI / SaaS / auth** -- the CLI plus `docs/PLAN.md` plus
  `.orchestrator/runs/` is the whole product surface for v0. A UI is a
  view onto that state, addable later without changing the state model.
- **Kubernetes / Redis / a vector database** -- there is no queue or shared
  cache to manage yet (one process, sequential ingest, thread-pooled
  per-run execution) and no semantic search need (PLAN.md + Change History
  is the memory; see `PLAN-SPEC.md`).
- **A generic agent framework (LangChain/CrewAI/LangGraph)** -- the
  orchestration logic here is small, typed, and specific to "move this
  repo toward this milestone." A general framework would add abstraction
  the domain doesn't need and make the deterministic/model-call boundary
  (spec section 23) harder to see and test.
- **Autonomous deploy / merge to protected branches** -- explicitly out of
  scope through v0 (spec section 2, 17); `READY_FOR_REVIEW` is a status a
  human acts on, not a trigger.
- **Agent-to-agent conversational coordination** -- workers communicate
  only through orchestrator-controlled structured state (task records,
  verification results, evidence files), never directly with each other
  (spec section 7).
