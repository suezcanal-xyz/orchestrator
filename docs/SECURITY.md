# Security model (v0)

This is a working list of what is actually enforced by code, what is only
requested by prompt, and what is a known gap -- written plainly so nobody
mistakes prompt instructions for a security boundary. If you are deciding
whether it's safe to point this at a repository with real credentials or
production access, read this file first, not `README.md`.

## Enforced by code

**Worktree isolation.** Every task runs in its own `git worktree` on a
branch named `orchestrator/<run-id>/<task-id>`, created from the detected
default branch. A task's file changes exist only in that worktree and
branch until the orchestrator itself commits them there; nothing a worker
does can appear on another task's worktree or on the protected branch
(`git.py`, tested in `tests/test_git.py`).

**No auto-merge, no auto-push, no auto-deploy.** Nothing in this codebase
calls `git push`, `git merge <protected>`, or any deploy/infra command.
`READY_FOR_REVIEW` is a status written to `docs/PLAN.md`; a human acts on
it. This is a structural property of what the code does, not a permission
setting that could be flipped.

**Credentials stripped from every worker subprocess.**
`workers.base._safe_subprocess_env()` sets `GIT_TERMINAL_PROMPT=0` and
disables `credential.helper` for the process tree (via the
`GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n` mechanism, git
>= 2.31) and clears `GIT_ASKPASS`/`SSH_ASKPASS`. If a worker attempts
`git push` or anything else needing auth, it fails closed instead of
succeeding silently via a credential manager already cached on the host,
or hanging on an interactive prompt.

**Orchestrator, not worker, performs the commit.** `engine.execute_task`
calls `git.commit_all()` itself after a worker call returns. A worker is
explicitly instructed not to commit; even if one does anyway, the
orchestrator's own commit is what evidence and verification are anchored
to, so there's always a known, reproducible state to point at.

**Verification has no model authority.** `verifier.py` runs exactly the
commands declared in a task or in `docs/PLAN.md`, captures exit code and
full output, and that is the only thing that decides pass/fail (spec
section 11). A worker's own claim of success is recorded as evidence, never
trusted.

## Requested by prompt only (not enforced)

Every worker call is prefixed with an explicit forbidden-operations list
(`workers/base.py: BOUNDARIES`) covering push/merge/force-push, commit,
secrets, `.env` files, CI/CD credentials, and production mutation. This is
a strong steer for a well-behaved model, but it is a prompt, not a sandbox
-- a worker that ignores it is not mechanically prevented from trying,
only from succeeding at the specific things listed above as "enforced by
code."

## Known gaps (v0)

**Codex on Windows runs with no OS-level sandbox.** Codex's own
`workspace-write` sandbox mode requires an elevated process to enforce a
restricted token on Windows; unelevated, it refuses to run at all
(`CreateProcess ... "windows unelevated restricted-token sandbox cannot
enforce split writable root sets"`). `workers/codex.py` falls back to
Codex's `danger-full-access` mode for any edit-mode call, meaning Codex's
own file-system and command sandboxing is off entirely for the duration of
that call. Mitigated by worktree isolation and the credential stripping
above, but not equivalent to a real sandbox: an edit-mode Codex call can
run arbitrary commands with the same OS privileges as the orchestrator
process itself. Do not run this against a machine or user account with
access you would not hand to that call directly. A real fix (a container,
a VM, or an elevated helper process with a proper restricted token) is
future work, not v0.

**Claude's read-only calls still get the Bash tool.** `workers/claude.py`
passes `Read Grep Glob Bash` (no `Edit`/`Write`) for review/inspect/
propose_tasks calls, since there is no narrower built-in split between
"can run commands" and "can only run read-only commands" in the CLI's tool
allowlist. In principle a read-only call could still shell out to write a
file. A stricter split (e.g. `--restricted` plus an explicit safe-command
allowlist) is a candidate for a later milestone, not implemented in v0.

**opencode read-only calls rely on the prompt, not a flag.**
`workers/opencode.py` omits `--auto` for review/inspect/propose_tasks
calls, so opencode falls back to its own permission behaviour with the
BOUNDARIES prompt telling it not to edit. There is no verified
CLI-enforced read-only mode wired here; treat an opencode read-only call
as "asked nicely", same class of gap as the Claude Bash note above.

**The onboarding dashboard has no auth.** `orchestrator onboarding` binds
`127.0.0.1` and is single-user by design. Anything that can reach that
port can trigger a run, scaffold files, and spawn a login command. Do not
bind it to `0.0.0.0`, port-forward it, or run it on a shared host. The
`/api/login/{worker}` route spawns a fixed command (`codex login`, etc.)
with no shell and no user-supplied arguments; it never receives or stores
a credential (the worker CLI's own OAuth flow does).

**`AGENTS.md`/`CLAUDE.md` in a target repo are read, not trusted.**
`context.py` includes their content in the context block handed to a
worker, but the orchestrator does not execute anything they say and does
not grant extra permissions based on their content (spec section 10). A
malicious or compromised target repo could still try to prompt-inject a
worker through these files; the boundaries above (worktree isolation,
no-push, orchestrator-owned commits) are what actually contain the blast
radius, not trust in repository-supplied instructions.

**No network egress control.** Nothing here restricts what a worker
process can reach over the network (it inherits normal outbound access).
If a task must run against a repo where exfiltration is a real concern,
that needs an external network boundary (firewall, proxy, disconnected
CI runner) -- out of scope for v0.

## Practical guidance

- Point this at repositories and machines you'd be comfortable handing an
  unsupervised shell to, until the Codex sandbox gap above is closed.
- Review a `BLOCKED` or `READY_FOR_REVIEW` run's diffs before merging
  anything by hand; nothing here merges for you.
- Keep real secrets out of the working tree entirely where possible
  (fetch them at deploy time, not commit time) rather than relying on the
  prompt-level "don't touch `.env`" instruction.
