"""Deterministic, capability-based worker selection."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkerProfile:
    worker: str
    operations: list[str]
    edit_capable: bool = False
    read_only_strength: int = 0
    structured_output: bool = False
    context_window_class: int = 0
    multimodal: bool = False
    cost_class: int = 0
    latency_class: int = 0
    sandbox_class: int = 0
    provider: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    selected: WorkerProfile
    eligible_workers: list[str] = field(default_factory=list)


def route_worker(
    workers: list[WorkerProfile], *, operation: str, required_capabilities: set[str]
) -> RoutingDecision:
    eligible = [
        worker
        for worker in workers
        if operation in worker.operations
        and ("edit" not in required_capabilities or worker.edit_capable)
    ]
    if not eligible:
        raise ValueError(f"no eligible worker for {operation}")
    eligible.sort(
        key=lambda worker: (worker.cost_class, worker.latency_class, worker.worker)
    )
    return RoutingDecision(
        selected=eligible[0], eligible_workers=[worker.worker for worker in eligible]
    )
