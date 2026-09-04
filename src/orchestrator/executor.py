"""Policy-enforced local execution boundary for future hardened runners."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class ExecutorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionPolicy:
    allowed_roots: list[Path]
    read_only: bool = False
    allowed_commands: set[str] = field(default_factory=set)
    timeout_seconds: int = 600


class LocalExecutor:
    def __init__(self, policy: ExecutionPolicy) -> None:
        self.policy = policy

    def validate_cwd(self, cwd: Path) -> Path:
        resolved = cwd.resolve()
        if not any(
            resolved.is_relative_to(root.resolve())
            for root in self.policy.allowed_roots
        ):
            raise ExecutorError(f"execution path outside allowed roots: {resolved}")
        return resolved

    def run(
        self, command: str, *, cwd: Path, writes: bool = False
    ) -> subprocess.CompletedProcess:
        resolved = self.validate_cwd(cwd)
        if writes and self.policy.read_only:
            raise ExecutorError("write operation rejected by read-only policy")
        executable = command.strip().split(maxsplit=1)[0] if command.strip() else ""
        if (
            self.policy.allowed_commands
            and executable not in self.policy.allowed_commands
        ):
            raise ExecutorError(f"command is not allowed: {executable}")
        return subprocess.run(
            command,
            shell=True,
            cwd=str(resolved),
            capture_output=True,
            text=True,
            check=False,
            timeout=self.policy.timeout_seconds,
        )
