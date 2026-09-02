---
project: your-project-name
current_version: 0.0.0
target_version: 0.1.0
active_milestone: name-your-first-milestone
status: IN_PROGRESS
---
# PROJECT PLAN

## Project

One paragraph: what this project is, in plain language.

## Strategic Objective

Why this project exists and what it is ultimately for. Not a feature list --
the reason the feature list would exist.

## Current Version

0.0.0 -- what actually ships today.

## Target Version

0.1.0 -- what "done" for the active milestone means, in version terms.

## Active Milestone

Name and one-paragraph description of the milestone currently in progress.
Only one milestone should be active at a time.

## Current State

A short, honest snapshot of what works, what's half-built, and what's
known-broken right now. Update this every run; do not let it go stale.

## Requirements

The durable requirements for the active milestone, as a list. Each should
be specific enough that a verification command could plausibly prove it.

- requirement one
- requirement two

## Known Bugs

- description of bug, with a file:line reference if known

## Tasks

This section is regenerated automatically from the structured task store
(`.orchestrator/state/tasks.json`) every time the orchestrator runs. Do not
hand-edit it; edit `## Requirements` / `## Known Bugs` and let the next
`orchestrator ingest` or `orchestrator run` reconcile it into tasks.

_No tasks yet._

## Dependencies

External services, other repositories, or ordering constraints this
project's milestone depends on.

## Acceptance Criteria

One line per criterion, in the same order as `## Verification Commands`
below -- position N here is proven by position N there. This is what
`orchestrator verify` and the final VERDICT.md are computed from.

- criterion one
- criterion two

## Verification Commands

- pytest tests/
- npm run build

## Evidence

Pointers into `.orchestrator/runs/<run-id>/` for anything worth citing by
hand (a specific test run, a specific diff). Most evidence lives in the
run directories themselves and does not need to be copied here.

## Decisions

Durable decisions and their rationale, so the next person (or the next run)
does not re-litigate them. One entry per decision.

## Blockers

Anything currently stopping progress that needs a human. Empty when clear.

## Completed Work

A short list of what the current milestone has actually finished, for
quick scanning. The authoritative record is `## Change History` below plus
task status in the task store; this section is a human-friendly summary.

## Deferred / Not Now

Requirements or ideas that were considered and explicitly deferred, with a
one-line reason, so they don't get silently re-proposed every run.

## Change History

Dated entries, oldest first, appended automatically by
`orchestrator ingest` / `orchestrator run` every time a human prompt is
reconciled into this plan. Do not delete past entries; this is the memory.
