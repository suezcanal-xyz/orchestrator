"""Typed, organization-agnostic registry of managed projects."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectDescriptor:
    id: str
    name: str
    repository: str
    local_path: str | None = None
    project_type: str | None = None
    default_branch: str = "main"
    work_branch: str | None = None
    plan_path: str = "docs/PLAN.md"
    status: str = "active"
    domains: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    publishes: list[str] = field(default_factory=list)
    sensitivity: str = "internal"
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> ProjectDescriptor:
        for key in ("id", "name", "repository"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise RegistryError(f"project descriptor requires non-empty {key!r}")
        lists = ("domains", "capabilities", "interfaces", "consumes", "publishes")
        if any(not isinstance(data.get(key, []), list) for key in lists):
            raise RegistryError("project descriptor collection fields must be lists")
        return cls(
            id=data["id"].strip(),
            name=data["name"].strip(),
            repository=data["repository"].strip(),
            local_path=data.get("local_path"),
            project_type=data.get("project_type"),
            default_branch=data.get("default_branch", "main"),
            work_branch=data.get("work_branch"),
            plan_path=data.get("plan_path", "docs/PLAN.md"),
            status=data.get("status", "active"),
            sensitivity=data.get("sensitivity", "internal"),
            metadata=data.get("metadata", {}),
            **{key: list(data.get(key, [])) for key in lists},
        )


class ProjectRegistry:
    def __init__(self, projects: list[ProjectDescriptor]) -> None:
        self._projects: dict[str, ProjectDescriptor] = {}
        for project in projects:
            if project.id in self._projects:
                raise RegistryError(f"duplicate project id: {project.id}")
            self._projects[project.id] = project

    @classmethod
    def load(cls, path: Path) -> ProjectRegistry:
        try:
            text = path.read_text(encoding="utf-8")
            raw = (
                json.loads(text)
                if path.suffix.lower() == ".json"
                else yaml.safe_load(text)
            )
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise RegistryError(f"cannot load registry {path}: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("projects"), list):
            raise RegistryError("registry must contain a projects list")
        return cls(
            [
                ProjectDescriptor.from_dict(item)
                for item in raw["projects"]
                if isinstance(item, dict)
            ]
        )

    def get(self, project_id: str) -> ProjectDescriptor:
        try:
            return self._projects[project_id]
        except KeyError as exc:
            raise RegistryError(f"unknown project id: {project_id}") from exc

    def all(self) -> list[ProjectDescriptor]:
        return list(self._projects.values())
