"""opencode CLI worker, invoked non-interactively via `opencode run`.

Contract (opencode >= 1.18):

    opencode run --dir <cwd> --format json [--model <provider/model>] [--auto] \
        --file <prompt_file> "Follow the instructions in the attached file."

The full (multi-KB, quote-heavy) prompt is written to a temp file and
attached with `--file`; the positional message is a short fixed ASCII
string. This mirrors why `codex.py` / `claude.py` pipe their prompt via
stdin: under `shell=True` on Windows (needed to launch a `.cmd` shim),
`cmd.exe` re-parses the whole command line and mangles embedded quotes, so
nothing variable-length or quote-containing goes in argv.

`--auto` auto-approves file edits. For read-only calls (review /
propose_tasks) it is omitted and the BOUNDARIES prompt is relied on; if a
future opencode version hard-blocks read-only runs on an interactive
permission prompt this will surface as a timeout, and `--auto` would then
be needed there too (documented in docs/SECURITY.md alongside the
equivalent Codex-on-Windows note).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

from orchestrator.workers.base import (
    Worker,
    WorkerResponse,
    _safe_subprocess_env,
    resolve_executable,
)

_POSITIONAL_MESSAGE = "Follow the instructions in the attached file exactly."


class OpenCodeWorker(Worker):
    name = "opencode"

    def __init__(self, executable: str = "opencode", model: str | None = None) -> None:
        self.executable = executable
        self.model = model

    def _invoke(
        self,
        cwd: Path,
        prompt: str,
        *,
        timeout: int,
        allow_edit: bool,
        structured: bool = False,
    ) -> WorkerResponse:
        exe, use_shell = resolve_executable(self.executable)

        with tempfile.TemporaryDirectory() as td:
            prompt_file = Path(td) / "prompt.md"
            prompt_file.write_text(prompt, encoding="utf-8")

            args = [exe, "run", "--dir", str(cwd), "--format", "json"]
            if self.model:
                args += ["--model", self.model]
            if allow_edit:
                args.append("--auto")
            args += ["--file", str(prompt_file), _POSITIONAL_MESSAGE]

            env = _safe_subprocess_env()
            # NVIDIA's OpenCode provider expects NVIDIA_API_KEY. Allow a
            # deployment to keep the same secret under the NIM_API_KEY name.
            env.setdefault("NVIDIA_API_KEY", env.get("NIM_API_KEY", ""))

            start = time.monotonic()
            try:
                proc = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    check=False,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
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
            raw = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
            summary, usage = _parse_events(proc.stdout)
            ok = proc.returncode == 0
            return WorkerResponse(
                ok=ok,
                summary=summary or (raw[-2000:] if not ok else ""),
                raw_output=raw,
                duration_seconds=duration,
                worker=self.name,
                cost_usd=usage.get("cost_usd"),
                error=None if ok else f"opencode run exited {proc.returncode}",
                extra={"usage": usage} if usage else {},
            )


def _iter_json_objects(text: str):
    """Yield JSON objects from `text`, whether it is a single array, a single
    object, or newline-delimited objects (opencode's `--format json` has
    varied across versions)."""
    text = text.strip()
    if not text:
        return
    try:
        whole = json.loads(text)
        if isinstance(whole, list):
            yield from (o for o in whole if isinstance(o, dict))
            return
        if isinstance(whole, dict):
            yield whole
            return
    except (json.JSONDecodeError, ValueError):
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            yield obj


_TEXT_KEYS = ("text", "content", "message", "result", "summary")
_TOKEN_KEYS = {
    "input_tokens": ("input", "prompt_tokens", "input_tokens", "tokens_in"),
    "output_tokens": ("output", "completion_tokens", "output_tokens", "tokens_out"),
    "cache_read_tokens": ("cache_read", "cache_read_tokens", "cached_tokens"),
}


def _deep_find_text(obj) -> str:
    """Best-effort: the deepest/last string under a known text key."""
    found = ""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _TEXT_KEYS and isinstance(v, str) and v.strip():
                found = v.strip()
            else:
                deeper = _deep_find_text(v)
                if deeper:
                    found = deeper
    elif isinstance(obj, list):
        for item in obj:
            deeper = _deep_find_text(item)
            if deeper:
                found = deeper
    return found


def _parse_events(stdout: str) -> tuple[str, dict]:
    last_text = ""
    usage: dict = {}
    for obj in _iter_json_objects(stdout):
        text = _deep_find_text(obj)
        if text:
            last_text = text
        _harvest_usage(obj, usage)
    return last_text, usage


def _harvest_usage(obj, usage: dict) -> None:
    if not isinstance(obj, dict):
        return
    for k, v in obj.items():
        if isinstance(v, dict):
            _harvest_usage(v, usage)
        elif isinstance(v, (int, float)):
            if k in ("cost", "cost_usd", "total_cost_usd"):
                usage["cost_usd"] = usage.get("cost_usd", 0.0) + float(v)
            for canonical, aliases in _TOKEN_KEYS.items():
                if k in aliases:
                    usage[canonical] = usage.get(canonical, 0) + int(v)
