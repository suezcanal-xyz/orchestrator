"""Immutable references to repository-local evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EvidenceRef:
    repo: str
    commit: str | None = None
    path: str | None = None
    line: int | None = None
    plan_section: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    verification_result: str | None = None
    external_url: str | None = None

    def __post_init__(self) -> None:
        if not self.repo:
            raise ValueError("evidence reference requires a repository")
        if not any(
            (self.commit, self.path, self.plan_section, self.run_id, self.external_url)
        ):
            raise ValueError("evidence reference requires a locator")

    def to_dict(self) -> dict:
        return asdict(self)
