# Onboarding

Two ways to get from "just cloned this" to a first run: the dashboard, or
the CLI directly. They do the same things.

## The dashboard

```bash
pip install "suez-orchestrator[dashboard]"
orchestrator onboarding
```

This serves a single local page on `http://127.0.0.1:8765/` (localhost
only -- see `docs/SECURITY.md`, it has no auth and must not be exposed) and
opens a browser tab. Three steps, top to bottom:

1. **Connect accounts.** One row per agent CLI (`codex`, `claude`,
   `opencode`) with a status dot: green = authenticated, amber = installed
   but not logged in, red = not on PATH. **Connect** spawns that CLI's own
   login command (`codex login`, `claude auth login`, `opencode auth
   login`) in a new console window; you complete the OAuth flow there. The
   dashboard never sees a token -- the CLI stores it wherever it normally
   would. The row re-checks itself a few seconds later.

2. **Connect repository.** Paste an absolute path to a git repo and hit
   **Check**. You get its project name, current/target version, active
   milestone, and task count. If it has no `docs/PLAN.md` yet, a **Scaffold
   PLAN.md** button appears (same as `orchestrator init`).

3. **Start work.** Type a starting prompt, tick the workers to use, hit
   **Run**. Progress streams into the page as it happens (reconcile,
   per-task implement/verify/debug, done/blocked), ending with the VERDICT
   and the total cost of the run.

The dashboard is a thin shell over the CLI: `/api/doctor` is `orchestrator
doctor`, `/api/init` is `orchestrator init`, `/api/run` is `orchestrator
run`, and progress comes off the same `orchestrator.extensions` hook bus
the console progress printer uses.

## The CLI directly

```bash
pip install suez-orchestrator

orchestrator doctor                       # what's installed and authenticated
codex login                               # ) whichever the doctor
claude auth login                         # ) report as not
opencode auth login                       # ) authenticated

orchestrator init ../my-repo              # scaffold docs/PLAN.md + AGENTS.md
$EDITOR ../my-repo/docs/PLAN.md           # fill in Requirements, Acceptance
                                          # Criteria, Verification Commands
orchestrator run ../my-repo --prompt "the first thing to fix"
```

A second prompt the next day continues from the same `docs/PLAN.md` and
`.orchestrator/state/tasks.json` -- it does not re-plan from zero.

## From inside Claude Code

`integrations/claude-code/skills/orchestrate` -- copy it into
`~/.claude/skills/` and say "orchestrate this: <request>" in any session.
See that skill's `SKILL.md`.
