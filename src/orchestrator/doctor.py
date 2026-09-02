"""`orchestrator doctor`: what agent CLIs are on this machine, and are they
usable (spec section 6 in spirit -- "workers must be replaceable", so
knowing what's actually available before a `run` fails halfway through is
worth a dedicated, fast, free command).

Every check here is local and free (no billed API call): `codex login
status`, `claude doctor`, `opencode providers list` all read local state
only. This command will never make a paid model call.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from orchestrator import extensions
from orchestrator.workers.base import WorkerError, resolve_executable

# CLI name -> whether a Worker ships for it in this repo today.
BUILTIN_WORKER_NAMES = {"codex", "claude", "opencode"}

# CLIs orchestrator knows how to look for.
KNOWN_CLIS = ("codex", "claude", "opencode")


@dataclass
class DoctorEntry:
    name: str
    found: bool
    path: str | None
    worker_registered: bool
    auth_note: str
    raw: str = ""


def _run_local(exe: str, extra_args: list[str], use_shell: bool, timeout: int = 20) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [exe, *extra_args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, shell=use_shell,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)


def _worker_registered(name: str) -> bool:
    return name in BUILTIN_WORKER_NAMES or name in extensions.registered_workers()


def check_codex(exe: str, use_shell: bool) -> DoctorEntry:
    ok, out = _run_local(exe, ["login", "status"], use_shell)
    note = out.splitlines()[0] if out else "could not determine login status"
    return DoctorEntry("codex", True, exe, _worker_registered("codex"), note, out)


def check_claude(exe: str, use_shell: bool) -> DoctorEntry:
    ok, out = _run_local(exe, ["doctor"], use_shell)
    note = (
        "installation healthy (run `claude doctor` for detail); "
        "authentication is confirmed only by actually running a task"
        if ok
        else "`claude doctor` reported an issue -- run it directly for detail"
    )
    return DoctorEntry("claude", True, exe, _worker_registered("claude"), note, out)


def check_opencode(exe: str, use_shell: bool) -> DoctorEntry:
    ok, out = _run_local(exe, ["providers", "list"], use_shell)
    if "0 credentials" in out:
        note = "installed but no provider is authenticated (`opencode providers login`)"
    elif ok:
        note = "installed, at least one provider authenticated"
    else:
        note = "could not read provider credentials"
    return DoctorEntry("opencode", True, exe, _worker_registered("opencode"), note, out)


_CHECKERS = {"codex": check_codex, "claude": check_claude, "opencode": check_opencode}


def run_doctor(clis: tuple[str, ...] = KNOWN_CLIS) -> list[DoctorEntry]:
    entries = []
    for name in clis:
        try:
            exe, use_shell = resolve_executable(name)
        except WorkerError:
            entries.append(DoctorEntry(name, False, None, _worker_registered(name), "not found on PATH"))
            continue
        checker = _CHECKERS.get(name)
        entries.append(
            checker(exe, use_shell)
            if checker
            else DoctorEntry(name, True, exe, _worker_registered(name), "no local health check defined for this CLI yet")
        )
    return entries


def format_report(entries: list[DoctorEntry]) -> str:
    lines = []
    for e in entries:
        if not e.found:
            lines.append(f"{e.name:<10} NOT FOUND")
            continue
        worker = "worker available" if e.worker_registered else "NO WORKER REGISTERED -- see docs/DEVELOPMENT.md"
        lines.append(f"{e.name:<10} found   {e.path}")
        lines.append(f"{'':<10}         {e.auth_note}")
        lines.append(f"{'':<10}         {worker}")
    return "\n".join(lines)
