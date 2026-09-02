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
orchestrator inspect <repo>
orchestrator ingest <repo> "<prompt>"
orchestrator plan <repo>
orchestrator run <repo> --prompt "<current request>"
orchestrator verify <repo>
orchestrator status <repo>
```

`run` performs ingest + plan + execution + verification in one pass, and is
the normal daily entry point:

```bash
orchestrator run --repo ../seacommons --prompt "Humanitarian is still missing locations and the NGO panel is wrong"
```

A second prompt the next day continues from the same `docs/PLAN.md` and
`.orchestrator/state/tasks.json` -- it does not start planning from zero.

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
