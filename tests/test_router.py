from orchestrator.router import WorkerProfile, route_worker


def test_router_selects_eligible_lowest_cost_worker_and_records_fallbacks():
    workers = [
        WorkerProfile(
            worker="expensive",
            operations=["implement"],
            edit_capable=True,
            cost_class=3,
        ),
        WorkerProfile(
            worker="nim", operations=["implement"], edit_capable=True, cost_class=1
        ),
    ]

    decision = route_worker(
        workers, operation="implement", required_capabilities={"edit"}
    )

    assert decision.selected.worker == "nim"
    assert decision.eligible_workers == ["nim", "expensive"]
