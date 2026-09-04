"""Evidence-backed, organization-agnostic project capability graph."""

from __future__ import annotations

from dataclasses import dataclass, field


class CapabilityGraphError(ValueError):
    pass


@dataclass(frozen=True)
class Capability:
    id: str
    project_id: str
    name: str
    status: str
    source_paths: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    sensitivity: str = "internal"
    version: str | None = None

    @property
    def key(self) -> str:
        return f"{self.project_id}:{self.id}"


@dataclass(frozen=True)
class CapabilityRelation:
    source: str
    relation: str
    target: str


class CapabilityGraph:
    def __init__(self, capabilities: list[Capability] | None = None) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._relations: list[CapabilityRelation] = []
        for capability in capabilities or []:
            if not capability.evidence_refs:
                raise CapabilityGraphError(
                    f"capability {capability.key} requires evidence"
                )
            if capability.key in self._capabilities:
                raise CapabilityGraphError(f"duplicate capability: {capability.key}")
            self._capabilities[capability.key] = capability

    def for_project(self, project_id: str) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.project_id == project_id]

    def add_relation(self, source: str, relation: str, target: str) -> None:
        if source not in self._capabilities or target not in self._capabilities:
            raise CapabilityGraphError("relation references unknown capability")
        candidate = CapabilityRelation(source, relation, target)
        if candidate in self._relations:
            return
        if relation == "depends_on" and self._has_path(target, source, "depends_on"):
            raise CapabilityGraphError(f"dependency cycle: {source} -> {target}")
        self._relations.append(candidate)

    def providers_for(self, capability_key: str) -> list[str]:
        return [
            r.source
            for r in self._relations
            if r.target == capability_key and r.relation == "consumes"
        ]

    def dependency_chain(self, capability_key: str) -> list[str]:
        if capability_key not in self._capabilities:
            raise CapabilityGraphError(f"unknown capability: {capability_key}")
        chain: list[str] = []
        pending = [capability_key]
        seen = {capability_key}
        while pending:
            current = pending.pop(0)
            dependencies = [
                relation.target
                for relation in self._relations
                if relation.source == current and relation.relation == "depends_on"
            ]
            for dependency in dependencies:
                if dependency not in seen:
                    seen.add(dependency)
                    chain.append(dependency)
                    pending.append(dependency)
        return chain

    def _has_path(self, start: str, target: str, relation: str) -> bool:
        seen: set[str] = set()
        pending = [start]
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(
                r.target
                for r in self._relations
                if r.source == current and r.relation == relation
            )
        return False
