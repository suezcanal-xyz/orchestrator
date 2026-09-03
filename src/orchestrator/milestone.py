"""Milestone / project status model (spec section 2, 19)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MilestoneStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    RELEASED = "RELEASED"


@dataclass
class ProjectMeta:
    """The structured frontmatter block that lives at the top of docs/PLAN.md."""

    project: str
    current_version: str
    target_version: str
    active_milestone: str
    status: MilestoneStatus = MilestoneStatus.IN_PROGRESS

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMeta":
        return cls(
            project=data["project"],
            current_version=str(data.get("current_version", "0.0.0")),
            target_version=str(data.get("target_version", "0.0.0")),
            active_milestone=data.get("active_milestone", ""),
            status=MilestoneStatus(data.get("status", MilestoneStatus.IN_PROGRESS.value)),
        )

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "active_milestone": self.active_milestone,
            "status": self.status.value,
        }


@dataclass
class CriterionResult:
    """One line of a VERDICT.md requirements table (spec section 19)."""

    description: str
    passed: bool
    detail: str = ""


@dataclass
class GateResult:
    """One `## Verification Commands` entry, run once in the integration
    worktree as an explicit milestone gate (ORCH-006)."""

    command: str
    passed: bool


@dataclass
class Verdict:
    project: str
    target_version: str
    criteria: list[CriterionResult] = field(default_factory=list)
    gate: list[GateResult] = field(default_factory=list)
    notes: str = ""

    @property
    def ready(self) -> bool:
        criteria_ok = len(self.criteria) > 0 and all(c.passed for c in self.criteria)
        gate_ok = all(g.passed for g in self.gate)  # empty gate is vacuously ok
        return criteria_ok and gate_ok

    @property
    def result_status(self) -> MilestoneStatus:
        return MilestoneStatus.READY_FOR_REVIEW if self.ready else MilestoneStatus.BLOCKED

    def render(self) -> str:
        lines = [
            "# VERDICT",
            "",
            f"Project: {self.project}",
            f"Target: {self.target_version}",
            "",
            "## Requirements",
            "",
        ]
        for c in self.criteria:
            mark = "PASS" if c.passed else "FAIL"
            detail = f"  ({c.detail})" if c.detail else ""
            lines.append(f"{mark}  {c.description}{detail}")
        if self.gate:
            lines += ["", "## Milestone Gate", "",
                      "(docs/PLAN.md `## Verification Commands`, run in the integration worktree)", ""]
            for g in self.gate:
                lines.append(f"{'PASS' if g.passed else 'FAIL'}  {g.command}")
        if self.notes:
            lines += ["", "## Notes", "", self.notes]
        lines += [
            "",
            "## Result",
            "",
            "READY FOR REVIEW" if self.ready else f"NOT READY FOR {self.target_version}",
            "",
        ]
        return "\n".join(lines)
