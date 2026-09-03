# Aligning a team on one workflow

The orchestrator has no server and no shared database. Team alignment comes
from two files that are already version-controlled, plus one shared config
repo.

## 1. `docs/PLAN.md` is the shared intent

Commit `docs/PLAN.md` in each managed repository. It is human-readable, it
carries the milestone acceptance criteria and verification commands, and
every `orchestrator run` that reconciles a prompt appends a dated
`## Change History` entry. When a teammate runs the orchestrator, their run
starts from the plan you committed, not from a blank slate -- and their
changes to the plan come back as a reviewable diff.

The `## Change History` section is the shared log of what was asked and
what was decided. Do not delete entries.

## 2. `.orchestrator/state/tasks.json` is the shared task graph

Also lives in the target repo (gitignored by default). If you want the task
graph itself shared rather than regenerated per clone, remove the
`.orchestrator/` line the tool adds to `.gitignore` and commit
`state/tasks.json` (leave `runs/` ignored -- those are large and
per-machine).

## 3. One `orchestrator-private` checkout is the shared behaviour

`orchestrator-private` (the private extension layer) is a normal git repo.
Share one checkout across the team and everyone gets identical runs:

- `config/repositories.yaml` -- the same repo list and local paths
- `config/workers.yaml` -- the same worker order per project (e.g. "Codex
  first on seacommons backend, Claude first on the web app")
- `config/policies.yaml` -- the same `max_debug_attempts`,
  `verification_timeout_seconds`, `context_char_budget` per project
- `projects/<name>/NOTES.md` -- the same private context folded into every
  worker prompt for that repo

Then the daily command is the same for everyone:

```bash
orchestrator-private run seacommons --prompt "..."
```

No one has to remember "use `--worker codex --max-debug-attempts 4` for
seacommons" -- it is in the config the whole team shares. Changing the
workflow is a reviewed commit to that repo, not tribal knowledge.

## What is still per-person

- CLI authentication (`codex login` etc.) -- each person logs into their
  own account; no shared credential, ever.
- Run evidence under `.orchestrator/runs/<id>/` -- local to whoever ran it.
  Point to a specific run in `docs/PLAN.md` `## Evidence` if it matters.
