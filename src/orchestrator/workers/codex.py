"""OpenAI Codex CLI worker, invoked non-interactively via `codex exec`."""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from orchestrator.workers.base import Worker, WorkerResponse, _safe_subprocess_env, resolve_executable


class CodexWorker(Worker):
    name = "codex"

    def __init__(self, executable: str = "codex") -> None:
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
        sandbox_mode = "danger-full-access" if allow_edit else "read-only"
        exe, use_shell = resolve_executable(self.executable)

        with tempfile.TemporaryDirectory() as td:
            last_msg_path = Path(td) / "last_message.txt"
            args = [
                exe, "exec",
                "-C", str(cwd),
                "-s", sandbox_mode,
                "--color", "never",
                "-o", str(last_msg_path),
                "-",  # read the prompt from stdin: avoids Windows cmd.exe
                      # command-line length/quoting limits on a multi-KB prompt
            ]
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    args,
                    input=prompt,
                    capture_output=True,
                    text=True,
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
            summary = ""
            if last_msg_path.exists():
                summary = last_msg_path.read_text(encoding="utf-8", errors="replace").strip()
            raw = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
            ok = proc.returncode == 0
            return WorkerResponse(
                ok=ok,
                summary=summary or (raw[-2000:] if not ok else ""),
                raw_output=raw,
                duration_seconds=duration,
                worker=self.name,
                error=None if ok else f"codex exec exited {proc.returncode}",
            )
