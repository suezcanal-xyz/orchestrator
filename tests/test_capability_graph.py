import pytest

from orchestrator.capability_graph import (
    Capability,
    CapabilityGraph,
    CapabilityGraphError,
)


def _capability(capability_id: str, project_id: str = "alpha") -> Capability:
    return Capability(
        id=capability_id,
        project_id=project_id,
        name=capability_id,
        status="ACTIVE",
        source_paths=["src/example.py"],
        evidence_refs=["src/example.py:1"],
    )


def test_graph_queries_capabilities_by_project_and_relation():
    graph = CapabilityGraph([_capability("ingest"), _capability("publish", "beta")])
    graph.add_relation("beta:publish", "consumes", "alpha:ingest")

    assert [c.id for c in graph.for_project("alpha")] == ["ingest"]
    assert graph.providers_for("alpha:ingest") == ["beta:publish"]


def test_graph_rejects_dangling_relation_and_dependency_cycle():
    graph = CapabilityGraph([_capability("one"), _capability("two")])
    with pytest.raises(CapabilityGraphError, match="unknown capability"):
        graph.add_relation("alpha:one", "depends_on", "missing:capability")

    graph.add_relation("alpha:one", "depends_on", "alpha:two")
    with pytest.raises(CapabilityGraphError, match="cycle"):
        graph.add_relation("alpha:two", "depends_on", "alpha:one")
