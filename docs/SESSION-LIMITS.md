# Session limits (design sketch -- not implemented)

Subscription plans for Codex and Claude have rolling usage windows (e.g. a
5-hour session allowance, plus a weekly cap). A long orchestrator run can
hit one mid-flight. Today the affected worker call just fails and the task
is retried or blocked like any other failure -- the run does not
understand *why* it failed and does not wait.

This document records the intended design so it is not re-invented later.
It is **not built in v0.2.0.**

## Intended behaviour

1. **Detect.** Each worker's `_invoke` classifies its own failure: a
   rate/session-limit hit looks different from a normal error (Claude:
   "usage limit reached", a `retry_after` / reset timestamp; Codex: a quota
   message). Return this as a distinct `WorkerResponse` state, e.g.
   `error_kind="rate_limited"` plus `reset_at` when the CLI gives one.

2. **Cool down, don't fail.** The engine marks that worker unavailable
   until `reset_at` (or a conservative default) instead of counting it as a
   failed attempt.

3. **Reassign if possible.** If another authenticated worker can take the
   pending task and does not overlap files with an in-flight one, move it.

4. **Pause and resume if not.** If every worker is cooled down, the run
   persists its state (the task graph already persists; add a
   `run-state.json` with "batch N of M, tasks X/Y pending") and schedules a
   resume at the earliest `reset_at`. `orchestrator run --watch` would be
   the daemon form; a bare `orchestrator run` would print "paused until
   HH:MM, re-run to resume" and exit cleanly.

5. **Never silently spin.** A paused run says exactly why and until when,
   in the run's `VERDICT.md` / manifest, same as a `BLOCKED` task does.

## Why deferred

It needs reliable limit-detection strings from each CLI (which change), a
resume protocol, and a scheduler. None of that is worth building before the
onboarding + frugal-execution work lands and gets used. The frugal-context
changes in v0.2.0 also reduce how often a run hits a limit in the first
place, which buys time to do this properly.
