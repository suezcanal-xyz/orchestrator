"""Structured decision support, deliberately separate from project plans."""

from __future__ import annotations

from dataclasses import dataclass, field


class RecommendationError(ValueError):
    pass


_PROMOTION_STATES = {"PROPOSED", "REVIEWED", "ACCEPTED", "REJECTED"}


@dataclass
class Recommendation:
    id: str
    finding_ids: list[str]
    objective: str
    rationale: str = ""
    affected_projects: list[str] = field(default_factory=list)
    proposed_changes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    expected_value: str = ""
    confidence: float = 0.0
    unknowns: list[str] = field(default_factory=list)
    promotion_state: str = "PROPOSED"

    def __post_init__(self) -> None:
        if self.promotion_state not in _PROMOTION_STATES:
            raise RecommendationError(
                f"invalid promotion state: {self.promotion_state}"
            )


class RecommendationStore:
    def __init__(self, recommendations: list[Recommendation] | None = None) -> None:
        self._items = {item.id: item for item in recommendations or []}

    def get(self, recommendation_id: str) -> Recommendation:
        try:
            return self._items[recommendation_id]
        except KeyError as exc:
            raise RecommendationError(
                f"unknown recommendation: {recommendation_id}"
            ) from exc

    def promote(self, recommendation_id: str, state: str) -> None:
        if state not in _PROMOTION_STATES:
            raise RecommendationError(f"invalid promotion state: {state}")
        self.get(recommendation_id).promotion_state = state
