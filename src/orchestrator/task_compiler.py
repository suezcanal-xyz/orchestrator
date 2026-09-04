"""Compile accepted organization recommendations into local task proposals."""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.recommendations import Recommendation


@dataclass(frozen=True)
class ProjectTaskProposal:
    project_id: str
    title: str
    acceptance: list[str]
    verification: list[str]
    status: str = "NEEDS_TRIAGE"
    external_prerequisites: list[str] = field(default_factory=list)


def compile_recommendation(recommendation: Recommendation) -> list[ProjectTaskProposal]:
    """Return proposals only; project-local reconciliation remains authoritative."""
    if recommendation.promotion_state != "ACCEPTED":
        return []
    changes = recommendation.proposed_changes or [recommendation.objective]
    return [
        ProjectTaskProposal(
            project_id=project_id,
            title=recommendation.objective,
            acceptance=list(changes),
            verification=["reconcile against the project-local PLAN.md"],
            external_prerequisites=[f"recommendation:{recommendation.id}"],
        )
        for project_id in recommendation.affected_projects
    ]
