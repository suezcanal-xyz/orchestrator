"""Common Worker interface (spec section 6).

The orchestrator owns planning, scheduling, verification, state, retries and
milestone status. Workers own code investigation, implementation, diagnosis
and review -- and nothing else. This module builds the four semantic prompts
(inspect/implement/review/debug/propose_tasks) once, in one place, so that
adding a third CLI-based worker later means implementing `_invoke()` only.

Safety boundaries actually enforced here (not just requested in the prompt):
  - every subprocess runs with credential helpers disabled and terminal
    prompts off, so a `git push`/`git merge --into main` attempted by the
    model fails closed instead of silently succeeding via cached credentials
    or hanging forever.
  - review and propose_tasks calls request a read-only / no-file-write mode
    from the underlying CLI.
  - the orchestrator -- not the worker -- performs the actual git commit
    after a worker call returns (see git.commit_all), so there is always a
    deterministic, known commit for evidence regardless of what the model did.

What is NOT enforced at this layer (documented in docs/SECURITY.md as a
known v0 gap): arbitrary shell commands run by an "edit" mode call are not
sandboxed by the orchestrator itself. Codex's own OS-level sandbox and
Claude's own tool allowlist are relied on for that; on Windows without
elevation, Codex's OS sandbox cannot enforce workspace-write, which is why
edit-mode Codex calls run with no sandbox at all with full disclosure.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.task_graph import Task


class WorkerError(Exception):
    pass


class WorkerTimeoutError(WorkerError):
    pass


@dataclass
class WorkerResponse:
    ok: bool
    summary: str
    raw_output: str
    duration_seconds: float
    worker: str
    session_id: str | None = None
    cost_usd: float | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)


BOUNDARIES = """Hard rules, non-negotiable:
- Work only inside the current directory (your isolated git worktree). Do not touch files outside it.
- Do NOT run `git push`, `git merge` onto another branch, `git rebase` onto another branch, or any force-push. (These will fail closed even if attempted -- no credentials are available to this process.)
- Do NOT commit. The orchestrator commits your work deterministically after you finish.
- Do NOT modify secrets, `.env` files containing real values, CI/CD deploy credentials, or infrastructure-as-code that provisions production.
- Do NOT restart, redeploy, or mutate any production service or database.
- If a requirement is ambiguous or the fix requires a decision only a human can make, say so plainly in your summary instead of guessing."""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none specified)"


def _safe_subprocess_env() -> dict[str, str]:
    """Environment for any worker subprocess: git push/pull-credentials fail closed.

    GIT_TERMINAL_PROMPT=0 makes git fail immediately instead of hanging on an
    interactive prompt. The GIT_CONFIG_COUNT/KEY/VALUE trio (git >= 2.31)
    disables credential.helper for this process tree, so a push cannot
    silently succeed using credentials already cached by Git Credential
    Manager / the OS keyring on the host machine.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.pop("GIT_ASKPASS", None)
    env.pop("SSH_ASKPASS", None)
    prior_count = int(env.get("GIT_CONFIG_COUNT", "0") or "0")
    env[f"GIT_CONFIG_KEY_{prior_count}"] = "credential.helper"
    env[f"GIT_CONFIG_VALUE_{prior_count}"] = ""
    env["GIT_CONFIG_COUNT"] = str(prior_count + 1)
    return env


def resolve_executable(name: str) -> tuple[str, bool]:
    """Resolve `name` on PATH and report whether it must be launched via a
    shell.

    On Windows, npm-installed CLIs (codex, claude) are typically `.cmd`
    shims, not `.exe` binaries. `CreateProcess` cannot execute a `.cmd`
    file directly (`subprocess.run([resolved_path, ...])` fails with
    `WinError 2`, "cannot find the file specified", even though the file
    exists) -- it has to go through `cmd.exe`, hence `shell=True` here.

    Note this is *not* by itself safe for arbitrary argument content:
    cmd.exe re-parses the whole joined command line with its own quoting
    rules, which do not compose cleanly with Python's `list2cmdline`
    (MSVCRT-style) escaping -- an argument containing double quotes can be
    silently mangled. That is exactly why every worker here passes its
    (multi-KB, quote-containing) prompt via stdin (`input=prompt`) rather
    than as a positional argument: the only arguments that go through
    `shell=True` are short flags and filesystem paths.
    """
    resolved = shutil.which(name)
    if resolved is None:
        raise WorkerError(f"{name!r} not found on PATH")
    use_shell = sys.platform == "win32" and resolved.lower().endswith((".cmd", ".bat"))
    return resolved, use_shell


class Worker(ABC):
    name: str = "base"

    @abstractmethod
    def _invoke(
        self,
        cwd: Path,
        prompt: str,
        *,
        timeout: int,
        allow_edit: bool,
        structured: bool = False,
    ) -> WorkerResponse:
        """Run the underlying CLI non-interactively in `cwd` with `prompt`.

        allow_edit=False must request a read-only / no-file-write mode from
        the CLI. structured=True means the caller expects the response
        summary to be a single JSON object and nothing else.
        """
        raise NotImplementedError

    # -- semantic operations (spec section 6) --------------------------------

    def inspect(self, cwd: Path, question: str, context_block: str, timeout: int = 300) -> WorkerResponse:
        prompt = (
            f"{BOUNDARIES}\n\n# Inspection request\n\n## Repository context\n{context_block}\n\n"
            f"## Question\n{question}\n\nDo not edit any files. Answer plainly and concretely, "
            f"citing file paths and line numbers where relevant."
        )
        return self._invoke(cwd, prompt, timeout=timeout, allow_edit=False)

    def implement(self, cwd: Path, task: "Task", context_block: str, timeout: int = 1800) -> WorkerResponse:
        prompt = (
            f"{BOUNDARIES}\n\n# Task {task.id}: {task.title}\n\n"
            f"## Repository context\n{context_block}\n\n"
            f"## Acceptance criteria\n{_bullets(task.acceptance)}\n\n"
            f"## Verification commands (will be run after you finish, by the orchestrator)\n"
            f"{_bullets(task.verification)}\n\n"
            f"## What to do\nImplement this task completely inside the current working directory. "
            f"Add or update tests as needed. You may run local commands to check your work "
            f"(the verification commands above will also be run for you afterward), but do not commit.\n\n"
            f"When done, give a short plain-text summary of what changed and why."
        )
        return self._invoke(cwd, prompt, timeout=timeout, allow_edit=True)

    def review(
        self, cwd: Path, task: "Task", diff_text: str, context_block: str, timeout: int = 900
    ) -> WorkerResponse:
        prompt = (
            f"{BOUNDARIES}\n\n# Review task {task.id}: {task.title}\n\n"
            f"## Repository context\n{context_block}\n\n"
            f"## Acceptance criteria\n{_bullets(task.acceptance)}\n\n"
            f"## Diff to review\n```diff\n{diff_text[:8000]}\n```\n\n"
            f"Actively look for: requirement mismatch, regressions, unhandled edge cases, "
            f"legacy or duplicated logic, unnecessary complexity, incorrect assumptions, "
            f"fake or stubbed behavior, missing tests.\n\n"
            f"Do not edit any files. Respond with a verdict line, exactly `APPROVE` or "
            f"`REQUEST_CHANGES`, followed by a bullet list of concrete issues (empty if APPROVE)."
        )
        return self._invoke(cwd, prompt, timeout=timeout, allow_edit=False)

    def debug(self, cwd: Path, task: "Task", evidence_block: str, timeout: int = 1800) -> WorkerResponse:
        prompt = (
            f"{BOUNDARIES}\n\n# Debug task {task.id}: {task.title}\n\n"
            f"## Original acceptance criteria\n{_bullets(task.acceptance)}\n\n"
            f"## Evidence\n{evidence_block}\n\n"
            f"## What to do\nDiagnose and fix the failure inside the current working directory. "
            f"Make the smallest correct change that addresses the root cause, not just the symptom. "
            f"Do not commit.\n\nWhen done, give a short plain-text summary of the root cause and the fix."
        )
        return self._invoke(cwd, prompt, timeout=timeout, allow_edit=True)

    def propose_tasks(
        self, cwd: Path, prompt_text: str, plan_text: str, context_block: str, timeout: int = 600
    ) -> WorkerResponse:
        schema_hint = (
            '{\n'
            '  "classification": "NEW_REQUIREMENT" | "BUG" | "REGRESSION" | '
            '"CHANGE_TO_EXISTING_REQUIREMENT" | "PRIORITY_CHANGE" | "DEFER" | "REMOVE" | "QUESTION",\n'
            '  "change_history_entry": "one paragraph, plain text, describing what was found and decided",\n'
            '  "tasks": [\n'
            '    {"title": "...", "acceptance": ["..."], "verification": ["..."], '
            '"priority": "P0|P1|P2|P3", "files_hint": ["..."]}\n'
            "  ]\n"
            "}"
        )
        prompt = (
            f"{BOUNDARIES}\n\n# Reconcile a new request into the project plan\n\n"
            f"## Current PLAN.md\n{plan_text[:6000]}\n\n"
            f"## Repository context\n{context_block}\n\n"
            f"## New human request\n{prompt_text}\n\n"
            f"## What to do\nDo NOT edit any files. Investigate the repository (read-only) to check "
            f"whether this request is already covered, partially implemented, or contradicts existing "
            f"plan content.\n\nRespond with ONLY a JSON object matching this shape, no prose outside "
            f"the JSON:\n\n{schema_hint}\n\n"
            f'"tasks" may be empty if classification is QUESTION or DEFER. Keep tasks atomic and testable.'
        )
        return self._invoke(cwd, prompt, timeout=timeout, allow_edit=False, structured=True)
