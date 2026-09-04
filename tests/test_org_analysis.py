from orchestrator.org_analysis import analyze_registry


def test_org_analysis_reads_registered_repositories_without_mutation(tmp_path):
    repo = tmp_path / "alpha"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "PLAN.md").write_text("# PLAN\n", encoding="utf-8")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        f"projects:\n  - id: alpha\n    name: Alpha\n    repository: acme/alpha\n    local_path: {repo.as_posix()}\n",
        encoding="utf-8",
    )

    findings = analyze_registry(registry, "What is planned?")

    assert findings[0].affected_projects == ["alpha"]
    assert findings[0].evidence_refs == ["docs/PLAN.md"]
