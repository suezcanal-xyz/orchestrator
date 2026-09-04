"""Generic, strictly read-only repository analysis primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AnalysisRequest:
    repo: Path
    question: str


@dataclass(frozen=True)
class AnalysisFinding:
    id: str
    scope: str
    title: str
    summary: str
    severity: str
    confidence: float
    evidence_refs: list[str]
    affected_projects: list[str] = field(default_factory=list)
    affected_capabilities: list[str] = field(default_factory=list)
    category: str = "plan_code_divergence"
    unknowns: list[str] = field(default_factory=list)
    analyzer: str = "deterministic-plan-scan"


def analyze(request: AnalysisRequest) -> list[AnalysisFinding]:
    """Inspect only; this function never mutates repository state or plans."""
    plan = request.repo / "docs" / "PLAN.md"
    if not plan.is_file():
        return [
            AnalysisFinding(
                id="analysis-missing-plan",
                scope=str(request.repo),
                title="No project plan found",
                summary="A docs/PLAN.md is required before plan-to-code divergence can be assessed.",
                severity="medium",
                confidence=1.0,
                evidence_refs=[],
                category="documentation_drift",
                unknowns=[
                    "Repository implementation was not interpreted without a canonical plan."
                ],
            )
        ]
    return [
        AnalysisFinding(
            id="analysis-plan-code-baseline",
            scope=str(request.repo),
            title="Plan requires code-to-plan reconciliation",
            summary="The canonical plan was found; compare each planned task with implementation evidence before promotion.",
            severity="info",
            confidence=0.8,
            evidence_refs=["docs/PLAN.md"],
            unknowns=["No language-specific implementation analyzer is registered."],
        )
    ]
