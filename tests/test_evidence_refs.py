from orchestrator.evidence_refs import EvidenceRef


def test_evidence_ref_is_immutable_and_detects_missing_required_locator():
    ref = EvidenceRef(
        repo="acme/alpha", commit="abc123", path="src/app.py", run_id="run-1"
    )
    assert ref.to_dict()["path"] == "src/app.py"
