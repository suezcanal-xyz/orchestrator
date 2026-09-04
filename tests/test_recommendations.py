import pytest

from orchestrator.recommendations import (
    Recommendation,
    RecommendationError,
    RecommendationStore,
)


def test_recommendation_store_promotes_only_explicitly():
    store = RecommendationStore(
        [Recommendation(id="rec-1", finding_ids=["f-1"], objective="Fix drift")]
    )
    assert store.get("rec-1").promotion_state == "PROPOSED"
    store.promote("rec-1", "ACCEPTED")
    assert store.get("rec-1").promotion_state == "ACCEPTED"


def test_recommendation_store_rejects_unknown_state():
    with pytest.raises(RecommendationError, match="promotion"):
        Recommendation(
            id="rec-1", finding_ids=["f-1"], objective="Fix", promotion_state="DONE"
        )
