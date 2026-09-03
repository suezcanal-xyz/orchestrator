---
project: orchestrator
current_version: 0.2.0
target_version: 0.3.0
active_milestone: senior-pipeline-readiness
status: IN_PROGRESS
---
# PROJECT PLAN

## Project

`orchestrator` is a milestone-driven, multi-agent development control
plane: it moves an existing repository from its current state toward an
explicitly specified target milestone, using coding agents (Codex, Claude,
opencode) as workers and deterministic software for planning, scheduling,
verification, state and evidence. The central object is this file, not the
agent.

This is the orchestrator's own `docs/PLAN.md` -- it now manages itself.

## Strategic Objective

Make the orchestrator trustworthy on *senior, complex* pipelines: large
multi-stack repositories, security-sensitive changes, work that lives on a
feature branch rather than the default branch, and runs long enough to hit
a subscription usage window. v0.1-0.2 proved the closed loop on small
repos; v0.3 is about the failure modes that only show up at scale, which
`docs/FAILURE-MODES.md` catalogues.

## Current Version

0.2.0 -- closed development loop, onboarding + project-aware dashboards,
opencode worker, private extension layer (policies / workers / context
providers), per-task focused context and cost accounting, integration-
worktree verdict, `--base` / `--task` run scoping, `docs/FAILURE-MODES.md`.

## Target Version

0.3.0 -- "senior pipeline readiness". Done when a run against a large
feature-branch pipeline (the SeaCommons `feat/media-evidence-pipeline`
tasks SEAC-004..010 are the reference workload) can:

- pick its base branch from config, not a hand-passed flag;
- report a scoped run honestly (task succeeded vs milestone incomplete);
- refuse to call a milestone done when its acceptance criteria were never
  written;
- survive a worker session-limit mid-run and resume without losing
  completed work;
- give a worker enough context to work in an unfamiliar senior codebase.

## Active Milestone

`senior-pipeline-readiness`: the nine tasks below. One milestone active at
a time.

## Current State

The engine runs one prompt end to end: reconcile -> task graph ->
per-task worktree -> worker -> verify -> cross-model debug -> integration
worktree -> verdict. `--base` and `--task` exist but must be passed by
hand every run. The verdict conflates "a task I ran failed" with "the
milestone is not complete". Cost accounting shows `$0.0000` for Codex
because Codex emits no structured token count. Context for a task is its
`files_hint` contents plus a <=4000-char provider block -- thin for a
repository the size of SeaCommons, and the private context provider does
not follow the doc pointers inside a project's NOTES.md. A run that hits a
Claude/Codex session limit dies with a generic `ReconciliationError` or a
blocked task and does not resume.

## Requirements

- A managed project can declare the branch its work is based on; runs use
  it automatically.
- A run narrowed with `--task` reports its own outcome distinctly from the
  milestone's completeness.
- A milestone whose `## Acceptance Criteria` / `## Verification Commands`
  are empty produces a loud, recorded warning, and the verdict says its
  judgement is task-status-only.
- Codex cost/token display is honest: never a misleading `$0.0000` for a
  call that clearly did work.
- The private context provider folds in the project policy/architecture
  docs its NOTES.md points at, within a bounded budget.
- `## Verification Commands` run once, in the integration worktree, as an
  explicit milestone gate that can block `READY_FOR_REVIEW` even when
  every task is `DONE`.
- A worker session-limit signal is recognised, surfaced as a first-class
  run status with the reset time, and a re-run resumes from the completed
  tasks rather than starting over.
- Cross-model review can return "changes requested" and loop back to
  implement, not only annotate.
- The scheduler serialises two tasks that touch the same file even when
  their `files_hint` lists differ, and reports a likely conflict before
  execution, not at verdict time.

## Known Bugs

- Verdict of a `--task`-scoped run reads `BLOCKED` / `NOT READY` when the
  scoped task actually succeeded (the other milestone tasks were simply
  not in scope). Observed on SeaCommons SEAC-003.
- `VERDICT.md` `## Cost` shows `Total: $0.0000  Tokens: 83` for a
  335-second Codex implement -- Codex does not emit a structured usage
  block and the best-effort parser under-reports rather than saying so.
- `orchestrator_private.bootstrap.project_notes_context` folds NOTES.md in
  but ignores the `docs/AI_ENGINEERING_POLICY.md` / `docs/LEGACY.MD`
  pointers it contains.
- A worker session-limit kills the run: `reconcile` raises
  `ReconciliationError: ... session limit`, or the task blocks like any
  other failure, with no resume path.

## Tasks

_Regenerated automatically by the orchestrator from
`.orchestrator/state/tasks.json` -- do not hand-edit._

| ID | Title | Status | Priority | Depends on |
|---|---|---|---|---|
| ORCH-001 | Per-project `work_branch`: runs pick the base branch from config, not a flag | DONE | P1 | - |
| ORCH-002 | Scoped-run verdict: distinguish "task failed" from "milestone incomplete" | READY | P1 | - |
| ORCH-003 | Loud warning + recorded note when milestone acceptance criteria are undefined | READY | P2 | - |
| ORCH-004 | Honest Codex cost display: never a misleading `$0.0000` for real work | READY | P2 | - |
| ORCH-005 | Private context provider follows the doc pointers in a project's NOTES.md | READY | P2 | - |
| ORCH-006 | Explicit milestone gate: `## Verification Commands` run once, can block READY | READY | P2 | ORCH-003 |
| ORCH-007 | Recognise a worker session-limit as a first-class run status with reset time | READY | P1 | - |
| ORCH-008 | `orchestrator run --resume <run-id>`: continue from completed tasks | READY | P2 | ORCH-007 |
| ORCH-009 | Scheduler: serialise same-file tasks and flag likely conflicts before execution | READY | P3 | - |

## Dependencies

- Python 3.11+, `git` on PATH.
- `codex` / `claude` / `opencode` CLIs authenticated (live worker paths and
  the `docs/FAILURE-MODES.md` reference workload only; unit tests are
  fully mocked).
- No new third-party runtime dependencies in v0.3 (spec §21).

## Acceptance Criteria

- ORCH-001: a `repositories.yaml` entry with `work_branch: feat/x` makes
  `orchestrator-private run <proj> --task T` create the task worktree from
  `feat/x` with no `--base` flag; `orchestrator run` in a repo whose
  checked-out branch is not the default branch and with no `--base` prints
  a one-line hint naming the current branch.
- ORCH-002: after `engine.run(..., only_task_ids={"T"})` where `T` ends
  `DONE`, `RunResult` reports a scoped status that is not `BLOCKED`, and
  `VERDICT.md` states how many tasks ran, that they passed, and how many
  milestone tasks remain.
- ORCH-003: `build_verdict` on a plan whose `## Acceptance Criteria` is
  `_Not yet defined._` returns a verdict carrying a `notes` string that
  says the judgement is task-status-only, and `ingest` records the same in
  `## Blockers`.
- ORCH-004: `evidence.format_cost_section` shows `codex: usage not
  reported` (not `$0.0000`) when a Codex stage has zero counted tokens but
  a non-zero duration.
- ORCH-005: `project_notes_context` for a project whose NOTES.md contains
  `docs/LEGACY.MD` returns a dict that also includes that file's content
  (bounded to a per-doc char cap), and only for pointers that resolve
  inside the target repo.
- ORCH-006: a run where every task is `DONE` but a `## Verification
  Commands` entry fails in the integration worktree ends
  `NOT READY_FOR_REVIEW` with the failing command named under a
  "milestone gate" heading in `VERDICT.md`.
- ORCH-007: a worker response whose stderr/stdout matches a session-limit
  pattern makes `engine.run` finish with status `BLOCKED_SESSION_LIMIT`
  and a `reset_hint` field, rather than raising or looping debug.
- ORCH-008: `orchestrator run <repo> --resume <run-id>` starts from the
  task store's current state (skipping `DONE` tasks), reuses the prior
  run's `plan-before.md`, and writes its verdict into a new run directory
  that references the resumed id.
- ORCH-009: two `READY` tasks whose `files_hint` name different paths in
  the same file land in different batches, and a run over them logs a
  "possible overlap" line naming the shared file before executing.

## Verification Commands

- python -m pytest -q
- python -m pytest -q ../orchestrator-private
- ruff check src/ tests/

## Evidence

(populated by orchestrator runs under `.orchestrator/runs/`)

## Decisions

- 2026-09-03: The orchestrator adopts its own `docs/PLAN.md` -- it did not
  dogfood its own planning format before v0.3.
- 2026-09-03: v0.3 scope is deliberately the failure modes that only
  appear on senior/complex pipelines (see `docs/FAILURE-MODES.md`), not
  new agent capabilities. No web UI beyond the existing local dashboards,
  no server, no queue (spec §21).
- 2026-09-03: ORCH-007/008 (session-limit + resume) are the highest-value
  items for long runs and are P1/P2; the `docs/SESSION-LIMITS.md` design
  sketch is the starting point.

## Blockers

None.

## Completed Work

- v0.1.0: closed development loop (spec §22 acceptance scenario), CLI,
  PLAN parser, milestone model, task DAG, git worktree isolation, Codex +
  Claude workers, verifier, automated cross-model debugger, evidence tree.
- v0.2.0: onboarding + project-aware dashboards, opencode worker, private
  extension layer wired into runs, per-task focused context, per-run cost
  accounting, `orchestrator init` / `doctor`, integration-worktree
  verdict, `--base` / `--task` scoping, `PYTHONDONTWRITEBYTECODE` in
  verification, `docs/FAILURE-MODES.md`.

## Deferred / Not Now

- Task decomposition (a task spawning sub-tasks) -- would be its own
  milestone.
- Multi-run concurrency / multiple task stores -- v0 is one run at a time.
- Monorepo per-directory verification routing -- ORCH-009 is the minimum
  step; full routing is deferred.
- Feeding recurring-bug patterns back into prompts (`prompts/`, `skills/`
  in the private layer) -- deferred until there is a corpus.
- Any autonomous merge / deploy -- out of scope indefinitely (spec §19).

## Change History

### 2026-09-03 -- ORCH-001 DONE

`orchestrator-private` reads `work_branch:` from `repositories.yaml` and
uses it as the default for `run --base` (explicit `--base` still wins).
`orchestrator run` on a non-default branch with no `--base` now prints a
one-line hint to stderr naming the branch. `seacommons` is configured
with `work_branch: feat/media-evidence-pipeline`, so SEAC-004..010 now
run from the right branch with no flag.

### 2026-09-03

Adopted this file as the orchestrator's own plan. Set target v0.3.0
`senior-pipeline-readiness` from the post-mortem of the first live run on
a real external pipeline (SeaCommons `feat/media-evidence-pipeline`,
SEAC-003 DONE) and from `docs/FAILURE-MODES.md`. Nine tasks
ORCH-001..009; ORCH-001/002/007 are P1. Reference workload for "done":
SEAC-004..010 runnable end to end from config with honest reporting and
session-limit survival.
