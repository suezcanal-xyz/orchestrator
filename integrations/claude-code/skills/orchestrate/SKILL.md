---
name: orchestrate
description: Delegate a chunk of the current repository's work to `orchestrator`, which reconciles the request into docs/PLAN.md, splits it into independent tasks, and runs Codex and Claude as workers in parallel, isolated git worktrees, verifying and debugging automatically. Triggers on "orchestrate this", "manda a orchestrator", "delega a orchestrator", "let orchestrator handle X", or multi-step repo work the user wants split across agents instead of done inline.
---

# orchestrate

Wraps the `orchestrator` CLI (https://github.com/suezcanal-xyz/orchestrator)
so a request can be handed off without leaving this session. `orchestrator`
does the actual work: reconciles the request into `docs/PLAN.md`, splits it
into independent tasks, runs each in its own isolated git worktree with a
real worker (Codex/Claude, assigned round-robin), verifies with real
commands, debugs failures automatically (cross-model, up to 3 attempts),
and never touches the protected branch.

## Before running

Confirm `orchestrator` and at least one worker CLI are usable:

```bash
orchestrator doctor
```

If `orchestrator` itself isn't installed, install it first (editable from a
local checkout, or `pip install orchestrator` once published) and stop to
tell the user rather than guessing a path. If `doctor` shows no worker CLI
authenticated, tell the user and stop -- do not run without one.

## Running

```bash
orchestrator run . --prompt "<the user's request, verbatim or lightly cleaned up>"
```

Run via Bash with output streamed as it arrives, not captured and dumped
all at once -- `orchestrator run` prints live per-task progress (worker
started, verification pass/fail, debug attempts) specifically so this can
be relayed to the user while it's still running, not just summarized after
the fact. Only pass `--worker` explicitly if the user asked for a specific
assignment; the default (`claude`, `codex`) is fine otherwise.

If the user names a different target repository than the current working
directory, pass that path instead of `.`.

## After it finishes

- `READY_FOR_REVIEW`: report which tasks are DONE, point at the run
  directory (`.orchestrator/runs/<run-id>/`) for diffs and evidence, and
  say plainly that nothing was merged -- the human reviews and merges by
  hand.
- `BLOCKED`: report which task(s) and why (the outcome's `reason`), and
  point at `.orchestrator/runs/<run-id>/logs/<task-id>.*.log` for detail.
  Do not silently retry the whole run; report and stop.
- Never run `git push` or `git merge` on the orchestrator's behalf --
  merging is always the human's decision, never this skill's.
