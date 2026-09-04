import json

import pytest

from orchestrator.registry import ProjectRegistry, RegistryError


def test_registry_loads_multiple_project_descriptors_from_yaml(tmp_path):
    path = tmp_path / "projects.yaml"
    path.write_text(
        """
projects:
  - id: alpha
    name: Alpha
    repository: acme/alpha
    local_path: ../alpha
    project_type: service
    default_branch: main
    work_branch: develop
    plan_path: docs/PLAN.md
    status: active
    domains: [data]
    capabilities: [ingest]
    interfaces: []
    consumes: []
    publishes: [events]
    sensitivity: internal
""",
        encoding="utf-8",
    )

    registry = ProjectRegistry.load(path)

    assert registry.get("alpha").repository == "acme/alpha"
    assert registry.get("alpha").publishes == ["events"]


def test_registry_loads_json_and_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(
        json.dumps(
            {
                "projects": [
                    {"id": "alpha", "name": "Alpha", "repository": "acme/alpha"},
                    {"id": "alpha", "name": "Again", "repository": "acme/again"},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RegistryError, match="duplicate"):
        ProjectRegistry.load(path)


def test_registry_rejects_malformed_descriptors(tmp_path):
    path = tmp_path / "projects.yaml"
    path.write_text("projects:\n  - id: alpha\n    name: Alpha\n", encoding="utf-8")

    with pytest.raises(RegistryError, match="repository"):
        ProjectRegistry.load(path)
