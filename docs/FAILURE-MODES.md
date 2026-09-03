# How AI coding fails, and what the orchestrator does about each

This is the design rationale for the whole project, written as a catalogue.
Every mechanism in `orchestrator` exists because a coding agent, left to
run on its own, fails in one of the ways below. None of these are
hypothetical: each is annotated with a real incident, most of them from
the orchestrator's own development or from the first real review it ran on
another repository.

The through-line: **a coding agent is good at writing a plausible change
and bad at knowing whether the change is correct, complete, or safe.** The
orchestrator's job is to be the part that knows — deterministically,
with evidence — and to keep the agent inside that frame.

Legend for each entry:

- **Shape** — what the failure looks like in practice.
- **Seen** — a concrete instance.
- **Caught by** — the mechanism in this repo that addresses it today.
- **Gap** — what is still not handled.

---

## 1. Verification theatre

**Shape.** The agent reports success. The "proof" is either absent ("Fixed
successfully.") or is a command that does not actually exercise the claim —
a test that imports stale bytecode, a cached result, a test the agent
wrote to pass rather than to fail on regression.

**Seen.** The orchestrator's own CI, this week: a debug fix that changed
`a + b` to `a * b` (same byte length) was not picked up on the immediate
re-run because CPython reused the `.pyc` from the previous attempt — same
mtime-second, same size. The task was reported `BLOCKED` although the fix
was correct. Only fast machines hit it; slow ones crossed a one-second
boundary and got away with it. (`fix/verifier-pycache-leak`.)

**Caught by.** `verifier.py` runs the declared verification commands
itself, as subprocesses, and records `command / exit code / stdout /
stderr / duration / commit / diff / worker / attempt` for every run. A
worker's textual claim carries zero authority (`docs/ARCHITECTURE.md`,
spec §11). Verification subprocesses run with `PYTHONDONTWRITEBYTECODE=1`
so a stale `.pyc` can never mask a real fix. After a targeted debug fix,
the *regression* verification is re-run, not just the one failing command.

**Gap.** The orchestrator does not judge whether the declared verification
commands are *adequate* — if `PLAN.md` says the acceptance command is
`pytest tests/test_foo.py` and that file only tests the happy path, a
passing run still says `READY_FOR_REVIEW`. Acceptance-criteria quality is
a human review responsibility.

---

## 2. Partial fix / parallel-path blindness

**Shape.** The agent fixes the instance it is looking at and misses the
sibling. Two call sites, one shared helper; the agent patches one call
site. A guard exists on the secondary path and not the primary.

**Seen.** First real review the orchestrator ran on another repository
(SeaCommons, `feat/media-evidence-pipeline`). Finding SEAC-003: the
SSRF / redirect / private-IP guard had been added to
`media_evidence._fetch` — the secondary, evidence-storage fetch — while
the *primary* coordinate-extraction fetch (`x_media_utils._ocr_photo`,
`fetch_tweet_photos`, used by live OCR and by the backfill job) still used
a default `urllib` opener that follows 3xx redirects and does no
private-IP check. The hardening looked done; half the attack surface was
untouched.

**Caught by.** The context-building phase (`context.py`) is asked to
surface duplicate implementations and legacy vs current code before a
change, not after. Cross-agent review (spec §13) is explicitly told to
look for "requirement mismatch, regressions, legacy duplication". Task
`files_hint` plus a focused context block keep the reviewing worker's
attention on the blast radius, not just the diff.

**Gap.** Detection of "the same logical operation happens in another file"
is currently only as good as the reviewing model. There is no static
call-graph or dataflow analysis. A `register_verifier` that greps for the
parallel pattern is the private-layer workaround.

---

## 3. Dropped epistemics — the happy-path collapse

**Shape.** The agent implements the nominal flow and silently discards the
distinctions that carried the meaning. "Extracted" becomes "verified".
"Offline" becomes "absent". "The request failed" becomes "there is no
data". An `except: pass` turns an error into a plausible-looking empty
result.

**Seen.** SeaCommons review, 6 of 10 findings were this one failure mode:

- SEAC-006: `classify_media_outcome` returned `MEDIA_COORDINATES_FOUND`
  identically for a confirmed cross-engine OCR consensus and for a
  cross-engine *disagreement* — the "is this coordinate trustworthy"
  signal was computed and then thrown away.
- SEAC-005: the backfill reprocessor's `resolve_position` swallowed every
  fetch exception and continued; `fetch_tweet_photos` returned `[]` on any
  network or JSON error. An un-fetched image and an image that OCR'd to
  nothing landed in the same "still unpositioned" bucket. Separately, a
  transient `getaddrinfo` failure was mapped to
  `FETCH_PRIVATE_IP_BLOCKED` — a permanent, security-shaped verdict for a
  temporary condition.

**Caught by.** The private layer injects project invariants as context
(`register_context_provider`) — for SeaCommons, literally the lines
"source credibility is not location credibility", "a coordinate extracted
is not a coordinate verified", "an HTTP failure is not an empty dataset".
A review pass on `core/intel/` is instructed to check the change against
them. `PLAN.md` acceptance criteria are meant to be written *as* the
distinctions that must survive, not as "the function returns a value".

**Gap.** This is the failure mode the orchestrator is least able to catch
mechanically. The invariants have to be written down by someone who knows
the domain, and the review is still a model judgement. The orchestrator
makes it *systematic* (every run sees the invariants) but not *automatic*.

---

## 4. Removing a guardrail it does not understand

**Shape.** A safety gate — a land-mass check, a rate limiter, an auth
check, a bounds assertion — is in the way of making the test green, so the
agent weakens or removes it. The diff looks like a simplification.

**Seen.** SeaCommons SEAC-008: `apply_position` in the backfill job called
`nearest_sea_point` unconditionally. The only thing stopping a land event
from being "sea-snapped" to the nearest water was a separate `_is_land_case`
gate in `run()` operating on text truncated to 500 characters. A direct
call, or a land signal that appeared late in the message body, bypassed
the gate entirely — "never sea-snaps a land case" was not actually true.

**Caught by.** `docs/SECURITY.md` names forbidden operations. Risky
deletions require human review (spec §9): the orchestrator will not let a
worker delete suspected-legacy code on the model's say-so — it requires
evidence (no inbound references, a superseded implementation exists, tests
prove the replacement behaviour, the build succeeds without it). Legacy is
classified `CURRENT / LEGACY / DEPRECATED / GENERATED / VENDOR` with that
evidence attached.

**Gap.** "Weakening" a guard (widening a bound, moving a check upstream of
where it matters) is subtler than "deleting" one and is not specifically
detected. The `files_hint` / focused-context mechanism helps only if the
guard lives in a file the task already touches.

---

## 5. Provenance loss

**Shape.** The agent re-derives or re-fetches instead of threading the
original value through. The audit chain breaks: the thing you stored is
not provably the thing you acted on.

**Seen.** SeaCommons SEAC-007: `_capture_media_evidence` re-downloaded each
image URL via `_fetch`, independently of the bytes `_ocr_photo` had
actually run OCR on. The stored `sha256` and `original` were therefore not
provably the artifact the coordinate was extracted from — and every image
was fetched twice per job. For an evidence pipeline, "the hash of a
different download of the same URL" is not evidence.

**Caught by.** Every run is an evidence tree under
`.orchestrator/runs/<run-id>/`: `manifest.json`, `plan-before.md`,
`plan-after.md`, `tasks.json`, `evidence/`, `logs/`, `diffs/`,
`VERDICT.md`. The orchestrator's *own* work is fully reconstructable after
the fact — what was asked, what changed in the plan, what each agent did,
what passed, what failed, why the milestone was or was not reached
(spec §14).

**Gap.** The orchestrator enforces provenance for *its own* actions. It
does not analyse whether the *target code* preserves provenance — that
showed up only because a human review prompt asked for it.

---

## 6. Wrong-window retrieval / context myopia

**Shape.** The agent retrieves the N most-recent rows *globally* instead
of the N rows near the target. It reads the superseded config, the stale
doc, the old component, because that is what a naive search surfaced.

**Seen.** SeaCommons SEAC-009: `canonicalize_event` built thread and
lifecycle context from the 200 globally-most-recent rows from the same
source, rather than rows near the target row's own timestamp. Re-running
canonicalization over historical data therefore computed the wrong
`incident_lifecycle` — the "context" was always *now*, never *then*.

**Caught by.** Per-task focused context (`context.py`, `docs/COST.md`): a
task gets a trimmed repo map (budget `context_char_budget`, default 2500
chars) plus the contents of its `files_hint` files — not a full-repo dump
that buries the relevant window. Files are classified
`CURRENT / LEGACY / UNKNOWN / DEPRECATED / GENERATED / VENDOR` so the
worker is not handed a generated file as if it were source.

**Gap.** The classification is heuristic (path patterns, markers, git
recency). A legacy file with no `deprecated` marker and a recent
touch-commit can still be presented as current.

---

## 7. Non-determinism read as progress

**Shape.** A flaky test passes on retry and the agent — or the CI, or the
human — concludes it is fixed. Timing-dependent behaviour, order-dependent
tests, network in the test path.

**Seen.** Same incident as #1, from the other side: before the `.pyc` root
cause was found, re-running the failed CI job made it green. "It passed on
retry" was treated as "it was flaky and is fine" for longer than it should
have been. The real fix (#1) came from asking *why* the retry passed.

**Caught by.** The verdict is deterministic: acceptance commands are run
against a single integration worktree with every `DONE` task branch merged
in (`fix/verdict-integration-worktree`), not against whatever state
happens to be checked out. Every debug attempt is recorded, including the
failures — `docs/SECURITY.md` and spec §12: "Do not hide unsuccessful
attempts." After a targeted fix, regression verification runs before the
task is allowed to be `DONE`.

**Gap.** The orchestrator does not run a suspicious verification command
multiple times to check for flakiness. A test that is 90%-green will be
taken at its word on any given run.

---

## 8. Environment and platform assumptions

**Shape.** "Works on my machine." `.cmd` shim vs native binary, path
separators, shell-quoting rules, line endings, a tool assumed to be on
PATH.

**Seen.** The orchestrator's own dashboard, this week
(`fix/dashboard-login-spawn`): `/api/login/<worker>` did
`subprocess.Popen(["opencode", ...])` with the bare name. On Windows the
agent CLIs are `.cmd` shims that `CreateProcess` cannot execute directly —
the call raised, the route returned a 500 HTML page, and the frontend
threw trying to parse that as JSON. Also, `docs/PLAN.md` carrying
`project: SEACOMMONS` while the config keyed the project as `seacommons`
caused a *silent* fallback to default worker settings — a case-sensitivity
assumption that hid a misconfiguration rather than reporting it.

**Caught by.** `orchestrator doctor` checks the actual local tools — found,
on PATH, authenticated, worker registered — and never makes a billed call
to do it. Worktrees are real checkouts; verification runs the real
commands in the real tree, so a platform problem surfaces during the run,
not after a merge. `resolve_executable` centralises the `.cmd`/shell rule.

**Gap.** `doctor` covers the known agent CLIs. A project's own toolchain
(a specific Node version, a native build dependency) is not checked before
a run that will need it.

---

## 9. Silent fallback instead of a reported error

**Shape.** A lookup misses, and instead of failing loudly the code
substitutes a default. The run continues, produces output, and nobody
knows the configuration was wrong.

**Seen.** The `SEACOMMONS` vs `seacommons` case above: the per-project
worker order (`codex` first, for a backend-heavy repo) was silently
replaced by the global default (`claude` first) because the key did not
match. The run "worked" — with the wrong worker, and, on the day Claude's
usage window was exhausted, it then failed for a reason that had nothing
to do with the mismatch.

**Caught by.** The reconcile step now classifies each request explicitly
(`NEW REQUIREMENT / BUG / REGRESSION / CHANGE / PRIORITY / DEFER / REMOVE /
QUESTION`) and records a dated `## Change History` entry — a run that
found nothing to do says so (`NO_WORK`), it does not quietly proceed.
Project lookups are now case-insensitive *and* the resolved worker order
is printed at the top of every run.

**Gap.** There is no schema validation of the private config files. A
misspelled policy key (`max_debug_attempt`) is still ignored silently.

---

## 10. Plan drift and requirement amnesia

**Shape.** Every new prompt starts from zero. Contradictory requirements
accumulate. The agent forgets what "done" was two prompts ago, or
re-implements something that already exists because it did not look.

**Seen.** This is the failure the whole project is built around, so the
counter-example is the good one: the second review prompt run against
SeaCommons was correctly reconciled as *already covered* — "this request
is already covered by the 2026-09-03 BUG entry and tasks SEAC-003 through
SEAC-010; no contradiction or new atomic task was found." No duplicate
tasks were appended. The plan is the memory; the reconcile step reads it
before doing anything.

**Caught by.** One continuously-evolving `docs/PLAN.md` per project
(`docs/PLAN-SPEC.md`). A new prompt is *always* reconciled into the
existing file — a new file is never created for a new prompt. The
reconciliation algorithm (spec §18) takes `NEW PROMPT + CURRENT PLAN +
REPOSITORY REALITY` and produces a plan *update*, resolving contradictions
and recording decisions rather than appending.

**Gap.** Reconciliation quality is a model judgement. A subtly-contradictory
requirement ("must be fast" vs a new "must be exhaustive") can still be
recorded as two coexisting bullets rather than flagged.

---

## 11. Interruption fragility

**Shape.** A long run dies mid-flight because a subscription usage window
closed. The run does not understand *why* it failed, does not wait, and
does not resume — the partial work is stranded.

**Seen.** The first real SeaCommons reconcile, run with `claude`, died
with `ReconciliationError: ... You've hit your session limit — resets
2:40pm`. The whole ingest was lost; it had to be re-run from scratch with
`codex`.

**Caught by.** Nothing yet, honestly. `docs/SESSION-LIMITS.md` is a design
sketch, not an implementation — today the affected call just fails and the
task is retried or blocked like any other failure.

**Gap.** The whole thing. Intended: detect the limit signal, mark the run
`BLOCKED (session limit, resets HH:MM)` as a first-class status, checkpoint
after each completed task so a resume picks up where it stopped, and allow
degrading to a single available worker.

---

## 12. Overconfident self-review

**Shape.** An agent asked to review its own work rubber-stamps it. The
same blind spot that produced the bug produces the review that misses it.

**Seen.** Structural, not a single incident — but note that in this
session the *cross-model* pairing worked: Codex implemented a `subtract()`
fix, its own verification failed, Claude diagnosed and corrected it, and
verification then passed. Same-model self-debug would have had to find its
own mistake.

**Caught by.** Risk-based cross-agent review (spec §13): for P0/P1
changes, agent A implements and a *different* agent B reviews before the
verifier runs. Debug is cross-model by preference — the worker that
implemented a task is not the first choice to debug it.

**Gap.** "Risk" is currently just the task priority in `PLAN.md`. A P3
task that happens to touch an auth path is not automatically escalated to
a review.

---

## The honest version (for anyone deciding whether to adopt this)

The orchestrator does not make a coding agent correct. It makes the
*process* around the agent honest:

- The agent never decides it is done. A command with an exit code does.
- The verdict is measured against the combined result of the work, in a
  clean environment, or it does not count.
- Every attempt, including the failed ones, is on disk.
- The plan is the memory, and it is a file in your repo, not state in a
  server.
- Nothing is merged or deployed automatically.

Where the orchestrator is only as good as the model — reconciliation
quality, "is this the same logical operation elsewhere", "does this change
preserve the domain's invariants" — this document says so plainly rather
than implying the scaffold has closed the gap. The scaffold makes those
judgements *systematic and reviewable*. It does not make them *automatic*.

The failure modes above are numbered so they can be cited. If you hit one
that is not here, add it.
