from orchestrator.analysis import AnalysisFinding, AnalysisRequest, analyze


def test_analysis_reports_plan_code_divergence_without_writing(tmp_path):
    repo = tmp_path / "demo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "PLAN.md").write_text(
        "# PLAN\n\n## Tasks\n\n- Add payment API\n", encoding="utf-8"
    )
    before = (repo / "docs" / "PLAN.md").read_text(encoding="utf-8")

    findings = analyze(
        AnalysisRequest(repo=repo, question="What is missing from the plan?")
    )

    assert all(isinstance(finding, AnalysisFinding) for finding in findings)
    assert findings[0].category == "plan_code_divergence"
    assert findings[0].evidence_refs == ["docs/PLAN.md"]
    assert (repo / "docs" / "PLAN.md").read_text(encoding="utf-8") == before


def test_analysis_keeps_unknowns_explicit_when_the_plan_is_missing(tmp_path):
    findings = analyze(AnalysisRequest(repo=tmp_path, question="What is missing?"))

    finding = findings[0]
    assert finding.category == "documentation_drift"
    assert finding.confidence == 1.0
    assert finding.unknowns
    assert finding.evidence_refs == []
