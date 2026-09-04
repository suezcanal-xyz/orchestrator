from orchestrator.recommendations import Recommendation
from orchestrator.task_compiler import compile_recommendation


def test_accepted_recommendation_compiles_separate_proposals_per_project():
    recommendation = Recommendation(
        id="rec-1",
        finding_ids=["f-1"],
        objective="Align shared interface",
        affected_projects=["alpha", "beta"],
        proposed_changes=["Expose stable event schema"],
        promotion_state="ACCEPTED",
    )

    proposals = compile_recommendation(recommendation)

    assert [proposal.project_id for proposal in proposals] == ["alpha", "beta"]
    assert all(proposal.status == "NEEDS_TRIAGE" for proposal in proposals)
    assert all(
        proposal.external_prerequisites == ["recommendation:rec-1"]
        for proposal in proposals
    )


def test_unaccepted_recommendation_cannot_compile_tasks():
    recommendation = Recommendation(
        id="rec-1", finding_ids=["f-1"], objective="Do work"
    )

    assert compile_recommendation(recommendation) == []
