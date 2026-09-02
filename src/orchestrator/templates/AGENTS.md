# AGENTS.md

Instructions for any coding agent (human-directed or orchestrator-directed)
working in this repository. The orchestrator reads this file as one input
to repository context (spec section 9, 10) -- it does **not** treat it as
unconditionally trusted; the orchestrator itself defines the actual
permission boundary (see `docs/SECURITY.md` in the orchestrator repo).
Fill in every section below for your project; delete this notice.

## Architecture

One paragraph plus a short list of the main components/services and how
they talk to each other. Link to a longer architecture doc if one exists.

## Directory ownership

Which top-level directories are safe to modify for which kinds of change,
and which are off-limits or need extra care.

```text
src/api/          -- backend, owned by <team/person>
src/web/          -- frontend, owned by <team/person>
migrations/        -- append-only; never edit a migration once merged
legacy/            -- do not extend; see "Known legacy areas" below
```

## Commands

The exact commands a worker (or a human) should run, copy-pasteable:

```bash
# install
...
# test
...
# lint
...
# typecheck
...
# build
...
```

These should match `## Verification Commands` in `docs/PLAN.md` where they
overlap -- this file documents how a human runs them by hand; PLAN.md is
what the orchestrator actually executes.

## Testing

What "passing" means for this project. Any tests that are expected to be
skipped or flaky, and why (a flaky test is a bug to fix, not a permanent
exception -- but if one exists today, say so honestly here).

## Forbidden operations

Anything a worker must never do in this repository specifically, beyond
the orchestrator's own hard rules (no push, no merge to protected branches,
no secrets, no production mutation -- those apply everywhere and don't need
repeating here). Examples: "never edit `db/schema.sql` directly, always add
a migration", "never touch `infra/` without a human in the loop".

## Source-of-truth files

Files that define behavior other files must stay consistent with (an
OpenAPI spec that generated clients depend on, a schema that migrations
must match, a design-token file that CSS should not duplicate).

## Database rules

Migration conventions, what needs a human review, what data must never be
touched by an automated task (PII, financial records, production rows).

## API contracts

Where the contract lives (OpenAPI/GraphQL schema/proto), and the rule for
changing it (e.g. "additive only without a version bump", "coordinate with
mobile team before removing a field").

## Deployment boundaries

What a worker may prepare (a PR, a migration file, a changelog entry) versus
what requires a human to actually trigger (a deploy, a production migration
run, a DNS change, a secret rotation).

## Known legacy areas

Parts of the codebase already known to be legacy/deprecated/dead, so a
worker doesn't have to rediscover this every time and doesn't touch it
without cause. Use the A/B/C/D classification from the orchestrator's
legacy-detection guidance if useful:

```text
A REQUIRED               -- still load-bearing, keep
B TEMPORARY COMPATIBILITY -- exists only to bridge old callers, has a removal plan
C DEAD LEGACY             -- provably unused, safe to remove with evidence
D UNKNOWN                 -- not yet investigated; do not assume either way
```

- `path/to/thing` -- classification, one-line reason, removal plan if B or C
