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
