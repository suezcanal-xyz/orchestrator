# Changelog

All notable changes to `orchestrator`. Dates are the milestone completion
date; the format follows [Keep a Changelog](https://keepachangelog.com).

## [0.3.0] -- 2026-09-03 -- "senior pipeline readiness"

The failure modes that only show up on large, feature-branch, security-
sensitive, long-running pipelines (`docs/FAILURE-MODES.md`), drawn from
the first live run against a real external repository. `orchestrator` now
manages its own `docs/PLAN.md`.

### Added
- **`--base <ref>`** -- base every task worktree (and the verdict's
  integration worktree) on a WIP feature branch instead of the default
  branch. `orchestrator-private` reads it from `work_branch:` in
  `repositories.yaml`. (ORCH-001)
- **`--task <id>`** (repeatable) -- run only the named tasks. A scoped run
  reports `run_status == "SCOPED_OK"` (exit 0) when its tasks finish, even
  though the milestone as a whole is not `READY_FOR_REVIEW`, and does not
  overwrite the milestone status. (ORCH-002)
- **`--resume <run-id>`** -- continue a prior run: skip reconcile, keep
  `DONE` tasks, carry the prior run's `plan-before.md` forward. Pairs with
  the new session-limit handling. (ORCH-008)
- **`orchestrator.limits`** -- a worker session / usage / rate-limit
  message is recognised; the run finishes `BLOCKED_SESSION_LIMIT` with a
  reset hint and exit code 75 (EX_TEMPFAIL), instead of raising or
  spinning the debug loop. (ORCH-007)
- **Explicit milestone gate** -- every `## Verification Commands` entry
  runs once in the integration worktree; a gate failure blocks
  `READY_FOR_REVIEW` even when every task is `DONE`. `VERDICT.md` gains a
  `## Milestone Gate` section. (ORCH-006)
- **`possible_overlap` progress event** -- warns when two scheduled tasks
  touch the same file (they are serialised, but their branches still
  collide at integration). (ORCH-009)
- `docs/PLAN.md` for the orchestrator itself -- it now dogfoods its own
  planning format.

### Changed
- `build_verdict` records a `notes` string when a milestone has no
  bulleted acceptance criteria / verification commands (the verdict is
  then task-status-only); `ingest` writes a one-time `## Blockers` line
  and clears it when the sections are filled. (ORCH-003)
- Cost display: a stage that ran >= 5 s but reported no cost and no tokens
  reads `usage not reported`, not a misleading `$0.0000  (0 tok)`. (ORCH-004)
- `orchestrator_private.bootstrap.project_notes_context` folds in the repo
  docs a project's `NOTES.md` points at by backtick-quoted path (bounded,
  repo-internal only). (ORCH-005)
- `TaskGraph.files_overlap` normalises path spellings (`./src/x.py` ==
  `src\x.py` == `src/x.py`); new `shared_files()` / `likely_overlaps()`.
  (ORCH-009)
- Project lookups in the private layer match the project name
  case-insensitively (`SEACOMMONS` in `PLAN.md` resolves to the
  `seacommons` config block).

## [0.2.0] -- 2026-09-02

### Added
- Local **onboarding dashboard** (`orchestrator onboarding`) and a
  **project-aware dashboard** in `orchestrator-private` (shape a plan from
  a prompt, review/correct the canonical sections, start the run).
- **opencode** worker.
- **Private extension layer** wired into runs: `repositories.yaml`,
  `workers.yaml`, `policies.yaml`, context providers.
- `orchestrator ingest` / `orchestrator-private ingest` -- reconcile-only.
- Per-task **focused context** (trimmed map + hinted files) and per-run
  **cost accounting** (`## Cost` in `VERDICT.md`, `usage.json`).
- `orchestrator init`, `orchestrator doctor`.
- **Integration-worktree verdict** -- milestone acceptance is judged
  against the merged result of the run's `DONE` task branches, not the
  untouched base branch.
- `docs/FAILURE-MODES.md`.

### Fixed
- Verification subprocesses run with `PYTHONDONTWRITEBYTECODE=1` so a
  stale `.pyc` from a previous attempt cannot mask a real debug fix.
- Windows: agent-CLI login and worker invocation resolve the `.cmd` shim
  through a shell instead of failing.

## [0.1.0] -- 2026-09-02 -- "closed development loop"

The spec section 22 acceptance scenario, end to end: open a repo, read
`docs/PLAN.md`, reconcile a prompt, produce independent tasks, run Codex
and Claude in isolated worktrees, verify with real commands, debug a
failure cross-model, update `PLAN.md`, produce `VERDICT.md`, leave the
protected branch untouched.

- CLI, `PLAN.md` parser/updater, milestone model, task DAG.
- Git worktree isolation, Codex + Claude workers, deterministic verifier,
  automated cross-model debugger.
- `.orchestrator/runs/<run-id>/` evidence tree.

[0.3.0]: https://github.com/suezcanal-xyz/orchestrator/releases/tag/v0.3.0
[0.2.0]: https://github.com/suezcanal-xyz/orchestrator/commits/main
[0.1.0]: https://github.com/suezcanal-xyz/orchestrator/commits/main
