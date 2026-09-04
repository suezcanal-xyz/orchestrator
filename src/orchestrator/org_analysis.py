"""Read-only organization analysis over a generic ProjectRegistry."""

from __future__ import annotations

from pathlib import Path

from orchestrator.analysis import AnalysisFinding, AnalysisRequest, analyze
from orchestrator.registry import ProjectRegistry


def analyze_registry(registry_path: Path, question: str) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    for project in ProjectRegistry.load(registry_path).all():
        if project.local_path is None:
            findings.append(
                AnalysisFinding(
                    id=f"org-missing-path-{project.id}",
                    scope=project.repository,
                    title="Registered project has no local path",
                    summary="Repository analysis was skipped because no local path is registered.",
                    severity="medium",
                    confidence=1.0,
                    evidence_refs=[],
                    affected_projects=[project.id],
                    category="verification_gap",
                    unknowns=["Current repository state is unavailable."],
                )
            )
            continue
        for finding in analyze(AnalysisRequest(Path(project.local_path), question)):
            findings.append(
                AnalysisFinding(
                    **{**finding.__dict__, "affected_projects": [project.id]}
                )
            )
    return findings
