# Token cost

The orchestrator runs coding agents on your own subscription (Codex on a
ChatGPT plan, Claude on a Claude plan, opencode on whatever provider you
authenticated). Every token a run spends is a token off your plan's
allowance, so the tool tries to spend few and shows you how many it spent.

## Where the savings come from

**Per-task focused context.** A task is handed a trimmed repository map
(budget: `context_char_budget`, default 2500 characters) plus the contents
of the files named in its `files_hint` -- not the full repo-wide context
map with every directory and every TODO marker. A task that only touches
`src/humanitarian/` does not pay to re-read the frontend tree on every
implement and every debug attempt. `orchestrator.context.focused_context`
builds this; `engine.run` calls it once per task.

**Reconciliation gets the full map, once.** The planning step
(`reconcile.py`) does need the whole picture, so it gets the run-wide
context block -- but only that one call does.

**Worker choice per project.** Via `orchestrator-private`'s
`config/workers.yaml` you can put a cheaper or single worker on
low-risk projects and reserve two-worker cross-model debugging for the
ones that need it. See `docs/TEAM.md`.

## Reading the `## Cost` section

Every `orchestrator run` writes a `## Cost` block into
`.orchestrator/runs/<id>/VERDICT.md` and a machine-readable
`.orchestrator/runs/<id>/usage.json`:

```
## Cost

Total: $0.4213
Tokens: 128,400 (96,000 in / 32,400 out / 71,000 cache-read)

By worker:
  claude: $0.3100  (89,200 tok)
  codex: $0.1113  (39,200 tok)

By stage:
  reconcile: $0.0400  (12,000 tok)
  implement: $0.2900  (78,400 tok)
  debug: $0.0913  (38,000 tok)
```

- **cache-read tokens** are input tokens served from the provider's prompt
  cache -- much cheaper than fresh input. A high cache-read fraction on the
  `debug` stage is the focused-context design working: the task prompt is
  stable across debug attempts.
- **by stage** tells you where a run's budget actually went. A run that is
  mostly `debug` cost is a run where verification kept failing -- look at
  the task's evidence, not just the total.

## What is approximate

`codex` does not emit a structured token count the way `claude -p --output-
format json` does, so codex figures are a best-effort parse of its output
and may be missing or coarse. Claude and opencode figures come straight
from the CLI's own usage payload.

When a stage ran for real (>= 5 seconds) but reported neither a cost nor
any token count, the `## Cost` section says `usage not reported (ran Ns;
this CLI emits no token count)` for that worker/stage and the `Total:`
line names the gap -- rather than printing a misleading `$0.0000  (0
tok)` that reads as "this was free".
