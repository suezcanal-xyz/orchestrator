---
project: calc-demo
current_version: 0.0.1
target_version: 0.1.0
active_milestone: basic-arithmetic
status: IN_PROGRESS
---
# PROJECT PLAN

## Project

calc-demo: a tiny arithmetic module used as the orchestrator's example
repository and closed-loop acceptance-test fixture.

## Strategic Objective

Demonstrate the orchestrator taking a repository from a known-incomplete
state to a milestone with verified, evidence-backed completion -- nothing
more. This project has no purpose beyond that.

## Current Version

0.0.1 -- `add()` works. `subtract()` is unimplemented. `multiply()` is
implemented but wrong (adds instead of multiplying).

## Target Version

0.1.0 -- all three operations correct and covered by a passing test each.

## Active Milestone

basic-arithmetic: `src/calc/__init__.py` exposes correct `add`, `subtract`
and `multiply` functions, each proven by its own test in
`tests/test_calc.py`.

## Current State

`add(a, b)` is correct. `subtract(a, b)` raises `NotImplementedError`.
`multiply(a, b)` returns `a + b` instead of `a * b`. `tests/test_calc.py`
already contains a test for each of the three functions; `test_subtract`
and `test_multiply` currently fail.

## Requirements

- subtract(a, b) returns a - b for any two integers
- multiply(a, b) returns a * b for any two integers
- add(a, b) continues to return a + b (no regression)

## Known Bugs

- `src/calc/__init__.py`: `subtract` raises `NotImplementedError` -- not implemented
- `src/calc/__init__.py`: `multiply` returns `a + b` instead of `a * b`

## Tasks

_Regenerated automatically by the orchestrator from
`.orchestrator/state/tasks.json` -- do not hand-edit._

_No tasks yet._

## Dependencies

None. Pure-Python, no external services.

## Acceptance Criteria

- subtract(5, 3) == 2
- multiply(4, 3) == 12
- add(2, 3) == 5 (no regression)

## Verification Commands

- python -m pytest tests/test_calc.py::test_subtract -q
- python -m pytest tests/test_calc.py::test_multiply -q
- python -m pytest tests/test_calc.py::test_add -q

## Evidence

(populated by orchestrator runs under `.orchestrator/runs/`)

## Decisions

- 2026-09-02: Kept the example deliberately tiny (one module, three
  functions) so the closed-loop test stays fast and legible rather than
  demonstrating scale.

## Blockers

None.

## Completed Work

- add(a, b) implemented and passing.

## Deferred / Not Now

- No additional operations (divide, power, etc.) -- out of scope for the
  basic-arithmetic milestone; would be a new milestone if ever needed.

## Change History

### 2026-09-02

Initial plan authored by hand as the orchestrator's example fixture. Not
yet reconciled through `orchestrator ingest` -- the first real run against
this repository should be the one that adds SC-style tasks for the two
known bugs above.
