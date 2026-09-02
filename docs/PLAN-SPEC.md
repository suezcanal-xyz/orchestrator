# docs/PLAN.md format

`docs/PLAN.md` is the canonical, continuously-evolving memory for one
project (spec section 1, 3). There is exactly one per project. A new human
prompt is always reconciled into the existing file (`reconcile.py`); a new
one is never created for a new prompt.

## Frontmatter

A YAML block at the top of the file carries the structured fields (spec
section 2), parsed by `orchestrator.milestone.ProjectMeta`:

```yaml
---
project: seacommons
current_version: 0.4.2
target_version: 0.5.0
active_milestone: humanitarian-data-stability
status: IN_PROGRESS
---
```

`status` is one of the five milestone statuses (spec section 2, 19):

```text
IN_PROGRESS
READY_FOR_REVIEW
BLOCKED
FAILED
RELEASED
```

`orchestrator` sets this field itself after computing a Verdict (see
below); it is not meant to be hand-edited to `READY_FOR_REVIEW` -- that
status means every acceptance criterion was actually run and passed.

## Sections

Everything after the frontmatter is a fixed sequence of `## ` sections,
parsed and rendered by `orchestrator.plan`. Unknown/custom sections found
in a hand-edited file round-trip unchanged; the canonical set is:

| Section | Who writes it | Purpose |
|---|---|---|
| Project | human (once) | what this project is |
| Strategic Objective | human | why it exists |
| Current Version | orchestrator | mirrors frontmatter |
| Target Version | orchestrator | mirrors frontmatter |
| Active Milestone | human + orchestrator | mirrors frontmatter + description |
| Current State | orchestrator (each run) | honest snapshot |
| Requirements | human + reconcile | durable, testable requirements |
| Known Bugs | human + reconcile | open bugs, with file:line where known |
| Tasks | **orchestrator only** | regenerated from `.orchestrator/state/tasks.json` every run -- do not hand-edit |
| Dependencies | human | external constraints |
| Acceptance Criteria | human | ordered list, paired with Verification Commands |
| Verification Commands | human | ordered list, paired with Acceptance Criteria |
| Evidence | human (optional) | pointers into `.orchestrator/runs/` worth citing |
| Decisions | reconcile + human | durable decisions and why |
| Blockers | orchestrator + human | what needs a human right now |
| Completed Work | orchestrator | human-friendly summary of DONE tasks |
| Deferred / Not Now | reconcile | explicitly deferred requirements, so they aren't silently re-proposed |
| Change History | reconcile (append-only) | dated entries, oldest first, never deleted |

## Acceptance Criteria <-> Verification Commands

These two sections are positionally paired: line *N* of `## Acceptance
Criteria` is proven true or false by actually running line *N* of
`## Verification Commands` (spec section 19). Keep them the same length
and in the same order. `orchestrator verify` / the final VERDICT.md is
computed by zipping them and running each command:

```markdown
## Acceptance Criteria

- humanitarian reports correctly geolocated
- NGO vessels correctly identified

## Verification Commands

- pytest tests/humanitarian/test_geolocation.py
- pytest tests/humanitarian/test_ngo_registry.py
```

If the two lists are not the same length (a criterion authored without a
matching command yet), `engine.build_verdict` falls back to one criterion
per non-deferred task, proved by that task's own DONE/BLOCKED status --
coarser, but still evidence-based, never a model's opinion.

## Change History

Dated, append-only, oldest first. Each reconciliation appends one entry
naming its classification and what changed:

```markdown
## Change History

### 2026-09-02

BUG: User reported NGO vessel panel incomplete. Inspection confirmed the
API exposes 14 vessels but the UI displays 7. Added task SC-052. Milestone
remains v0.5.0.
```

This -- plus the structured task store -- is the entire long-term memory
mechanism for v0. No vector database, no embeddings (spec section 18, 21):
a human or a worker can `grep` this file and get the real history.

## Tasks section vs. the task store

`.orchestrator/state/tasks.json` (schema: `schemas/task.schema.json`) is
the single source of truth for tasks -- structured, typed, with
dependencies and status. The `## Tasks` markdown section is a rendered
view of that store for humans reading the file; `PlanDocument.sync_task_section()`
regenerates it every run. Never hand-edit `## Tasks` expecting it to
change scheduling -- edit `## Requirements` and let the next
`orchestrator ingest`/`run` reconcile it into the task store.
