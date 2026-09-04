"""Anthropic Claude Code CLI worker, invoked non-interactively via `claude -p`."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from orchestrator.workers.base import (
    Worker,
    WorkerResponse,
    _safe_subprocess_env,
    resolve_executable,
)


class ClaudeWorker(Worker):
    name = "claude"

    def __init__(self, executable: str = "claude") -> None:
        self.executable = executable

    def _invoke(
        self,
        cwd: Path,
        prompt: str,
        *,
        timeout: int,
        allow_edit: bool,
        structured: bool = False,
    ) -> WorkerResponse:
        tools = (
            "Bash Edit Write Read Grep Glob" if allow_edit else "Read Grep Glob Bash"
        )
        exe, use_shell = resolve_executable(self.executable)
        permission_mode = "bypassPermissions"

        args = [
            exe,
            "-p",
            "--permission-mode",
            permission_mode,
            "--allowedTools",
            tools,
            "--output-format",
            "json",
            # no positional prompt: piped via stdin instead, below -- avoids
            # Windows cmd.exe command-line length/quoting limits on a
            # multi-KB prompt
        ]
        start = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                input=prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                env=_safe_subprocess_env(),
                timeout=timeout,
                shell=use_shell,
            )
        except subprocess.TimeoutExpired as e:
            return WorkerResponse(
                ok=False,
                summary="",
                raw_output=(e.stdout or "") + (e.stderr or ""),
                duration_seconds=float(timeout),
                worker=self.name,
                error=f"timed out after {timeout}s",
            )
        duration = time.monotonic() - start
        raw = proc.stdout

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            data = None

        if data is None:
            ok = proc.returncode == 0
            return WorkerResponse(
                ok=ok,
                summary=raw[-2000:],
                raw_output=raw + proc.stderr,
                duration_seconds=duration,
                worker=self.name,
                error=None
                if ok
                else f"claude -p exited {proc.returncode}: could not parse JSON output",
            )

        is_error = bool(data.get("is_error"))
        ok = proc.returncode == 0 and not is_error
        u = data.get("usage") or {}
        usage = {
            "input_tokens": int(u.get("input_tokens", 0) or 0),
            "output_tokens": int(u.get("output_tokens", 0) or 0),
            "cache_read_tokens": int(u.get("cache_read_input_tokens", 0) or 0),
            "cost_usd": data.get("total_cost_usd"),
        }
        return WorkerResponse(
            ok=ok,
            summary=str(data.get("result", "")),
            raw_output=raw,
            duration_seconds=duration,
            worker=self.name,
            session_id=data.get("session_id"),
            cost_usd=data.get("total_cost_usd"),
            error=None if ok else str(data.get("result") or f"exit {proc.returncode}"),
            extra={
                "num_turns": data.get("num_turns"),
                "subtype": data.get("subtype"),
                "usage": usage,
            },
        )
