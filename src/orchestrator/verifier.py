"""Automated, deterministic verification (spec section 11).

A worker saying "fixed successfully" has zero authority. A task is complete
only when its declared verification commands pass, run by this module, not
claimed by a model. This is plain subprocess plumbing -- no model calls.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class VerificationResult:
    command: str
    exit_code: int
    passed: bool
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    commit: str | None = None
    worker: str | None = None
    attempt: int = 1
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "passed": self.passed,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "commit": self.commit,
            "worker": self.worker,
            "attempt": self.attempt,
            "timestamp": self.timestamp,
        }


def run_command(
    command: str,
    cwd: Path,
    *,
    timeout: int = 600,
    commit: str | None = None,
    worker: str | None = None,
    attempt: int = 1,
    max_captured_chars: int = 20_000,
) -> VerificationResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        exit_code = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        exit_code = 124
        stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
        stderr = ((e.stderr or "") if isinstance(e.stderr, str) else "") + f"\n[verifier] timed out after {timeout}s"
    duration = time.monotonic() - start
    return VerificationResult(
        command=command,
        exit_code=exit_code,
        passed=exit_code == 0,
        stdout=stdout[-max_captured_chars:],
        stderr=stderr[-max_captured_chars:],
        duration_seconds=duration,
        commit=commit,
        worker=worker,
        attempt=attempt,
    )


def run_verification(
    commands: list[str],
    cwd: Path,
    *,
    timeout_per_command: int = 600,
    commit: str | None = None,
    worker: str | None = None,
    attempt: int = 1,
    stop_on_first_failure: bool = False,
) -> list[VerificationResult]:
    results = []
    for cmd in commands:
        r = run_command(
            cmd, cwd, timeout=timeout_per_command, commit=commit, worker=worker, attempt=attempt
        )
        results.append(r)
        if stop_on_first_failure and not r.passed:
            break
    return results


def overall_passed(results: list[VerificationResult]) -> bool:
    return len(results) > 0 and all(r.passed for r in results)


def failing(results: list[VerificationResult]) -> list[VerificationResult]:
    return [r for r in results if not r.passed]
