# orchestrator

A milestone-driven multi-agent development control plane.

`orchestrator` is not a generic agent framework. It automates one specific,
repetitive workflow: moving an existing software project from its current
state toward an explicitly specified target milestone, using coding agents
(Codex, Claude) as workers, and deterministic software for planning,
scheduling, verification and state.

The central object is not the agent. It is the project's canonical
`docs/PLAN.md`. Agents do not define completion; tests and milestone
acceptance criteria do.

```text
CURRENT USER PROMPT
        v
CURRENT REPOSITORY STATE
        v
CURRENT PLAN.md
        v
   RECONCILE
        v
UPDATED PLAN.md -> TASK GRAPH -> EXECUTION -> VERIFICATION -> DEBUG
        v
UPDATED PLAN.md
        v
NEXT ITERATION
```

## Install

```bash
pip install suez-orchestrator
# or, with the local onboarding dashboard:
pip install "suez-orchestrator[dashboard]"
```

## Quickstart (dashboard)

```bash
orchestrator onboarding
```

Opens a local page (localhost only) to connect your agent CLIs
(`codex` / `claude` / `opencode`), point at a repo, and run the first pass
with live progress and a cost total. See `docs/ONBOARDING.md`.

## Usage (CLI)

```bash
orchestrator doctor
orchestrator init <repo>                  # scaffold docs/PLAN.md + AGENTS.md
orchestrator inspect <repo>
orchestrator ingest <repo> "<prompt>"
orchestrator plan <repo>
orchestrator run <repo> --prompt "<current request>"
orchestrator verify <repo>
orchestrator status <repo>
```

`doctor` is the first thing to run on a new machine: it reports which agent
CLIs (codex, claude, opencode) are on PATH, whether each is authenticated,
and whether a Worker exists for it -- local checks only, never a billed API
call. All three ship as built-in workers.

`run` performs ingest + plan + execution + verification in one pass, and is
the normal daily entry point. It prints live per-task progress as it
happens (worker started, verification pass/fail, debug attempts) rather
than going silent until it returns:

```bash
orchestrator run ../seacommons --prompt "Humanitarian is still missing locations and the NGO panel is wrong"
```

A second prompt the next day continues from the same `docs/PLAN.md` and
`.orchestrator/state/tasks.json` -- it does not start planning from zero.

Every run records what it spent: a `## Cost` section in the run's
`VERDICT.md` and a `usage.json`, broken down by worker and by stage. Tasks
get a per-task focused context (their hinted files plus a trimmed map)
rather than the whole repo map every call, so a run stretches a Plus/Pro
subscription further. See `docs/COST.md`.

## Use it from inside Claude Code

Instead of leaving your chat session to run the CLI by hand, install the
`/orchestrate` skill and delegate straight from a prompt:

```bash
cp -r integrations/claude-code/skills/orchestrate ~/.claude/skills/
```

Then, in any Claude Code session: "orchestrate this: fix the humanitarian
panel" (or similar) runs `orchestrator doctor` + `orchestrator run` against
the current repo for you, streams progress back into the chat, and reports
DONE/BLOCKED per task plus where the diffs live -- without you touching a
terminal. See `integrations/claude-code/skills/orchestrate/SKILL.md` for
exactly what it does and doesn't do (it never pushes or merges).

## What this deliberately does not do

No SaaS, no cloud account, no hosted database, no auth server, no
Kubernetes, no Redis, no vector database, no autonomous deploy or merge, no
generic chat interface. The onboarding dashboard is an optional, local,
single-user page -- not a product surface. Session-limit-aware
pause/resume is designed (`docs/SESSION-LIMITS.md`) but not built. See
`docs/ARCHITECTURE.md` for the full list of what is kept out and why.

## Docs

- `docs/ONBOARDING.md` -- dashboard and CLI first-run
- `docs/TEAM.md` -- how a team shares one workflow
- `docs/COST.md` -- token spend, and where the savings come from
- `docs/ARCHITECTURE.md` -- module map
- `docs/PLAN-SPEC.md` -- the `docs/PLAN.md` format
- `docs/SECURITY.md` -- boundaries and known gaps
- `docs/DEVELOPMENT.md` -- setup, methodology, adding a worker

## Extending

The public core exposes five extension points so that project- or
organization-specific behavior (private prompts, policies, verification
commands, context providers, extra workers) can be registered without
modifying this repository. `orchestrator-private` is Suez Canal's own
extension layer and a worked example. See `orchestrator.extensions`,
`orchestrator.policy`, and `docs/ARCHITECTURE.md`.

## License

MIT. See `LICENSE`.
