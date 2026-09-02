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
pip install -e ".[dev]"
```

## Usage

```bash
orchestrator doctor
orchestrator inspect <repo>
orchestrator ingest <repo> "<prompt>"
orchestrator plan <repo>
orchestrator run <repo> --prompt "<current request>"
orchestrator verify <repo>
orchestrator status <repo>
```

`doctor` is the first thing to run on a new machine: it reports which agent
CLIs (codex, claude, opencode, ...) are on PATH, whether each is
authenticated, and whether a Worker exists for it -- local checks only,
never a billed API call.

`run` performs ingest + plan + execution + verification in one pass, and is
the normal daily entry point. It prints live per-task progress as it
happens (worker started, verification pass/fail, debug attempts) rather
than going silent until it returns:

```bash
orchestrator run ../seacommons --prompt "Humanitarian is still missing locations and the NGO panel is wrong"
```

A second prompt the next day continues from the same `docs/PLAN.md` and
`.orchestrator/state/tasks.json` -- it does not start planning from zero.

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

## What v0 deliberately does not do

No web UI, no SaaS, no auth, no Kubernetes, no Redis, no vector database,
no autonomous deploy, no generic chat interface. See `docs/ARCHITECTURE.md`
for the full list of things kept out of v0 and why.

## Repository layout

See `docs/ARCHITECTURE.md` for the module map and `docs/PLAN-SPEC.md` for
the `docs/PLAN.md` format this tool reads and writes.

## Extending

The public core exposes five extension points so that project- or
organization-specific behavior (private prompts, policies, verification
commands, context providers) can be registered without modifying this
repository. See `orchestrator.extensions` and `docs/ARCHITECTURE.md`.

## License

MIT. See `LICENSE`.
