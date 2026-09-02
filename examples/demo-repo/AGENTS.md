# AGENTS.md

## Architecture

One module, `src/calc/__init__.py`, three functions. No services, no
database, no API. Tests live in `tests/test_calc.py`.

## Directory ownership

```text
src/calc/    the only code that should change for this milestone
tests/       add/adjust assertions only if a requirement in docs/PLAN.md changed
docs/        docs/PLAN.md is the orchestrator's own file; edit Requirements/
             Known Bugs, not ## Tasks
```

## Commands

```bash
# test
python -m pytest tests/ -q
```

## Testing

`python -m pytest tests/ -q` must pass completely for the milestone to be
considered done. There are no known flaky or intentionally-skipped tests.

## Forbidden operations

None beyond the orchestrator's own standing rules (no push, no merge to
`main`, no commit -- the orchestrator commits your work).

## Source-of-truth files

`docs/PLAN.md` `## Acceptance Criteria` / `## Verification Commands` define
what "done" means. `tests/test_calc.py` is the executable form of that.

## Database rules

N/A -- no database.

## API contracts

N/A -- no API.

## Deployment boundaries

N/A -- this project is never deployed.

## Known legacy areas

None -- the whole repository is three functions, all current (category A).
