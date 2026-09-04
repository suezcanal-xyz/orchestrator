import pytest

from orchestrator.task_graph import CycleError, Task, TaskGraph, TaskGraphError


def make_task(id_, deps=None, files=None, status="READY", priority="P2"):
    return Task(
        id=id_,
        title=id_,
        status=status,
        depends_on=deps or [],
        files_hint=files or [],
        acceptance=["ok"],
        verification=["true"],
        priority=priority,
    )


def test_topological_order_respects_dependencies():
    g = TaskGraph(
        [make_task("A"), make_task("B", deps=["A"]), make_task("C", deps=["B"])]
    )
    order = g.topological_order()
    assert order.index("A") < order.index("B") < order.index("C")


def test_cycle_detected():
    g = TaskGraph([make_task("A", deps=["B"]), make_task("B", deps=["A"])])
    with pytest.raises(CycleError):
        g.topological_order()


def test_dangling_dependency_rejected():
    g = TaskGraph([make_task("A", deps=["GHOST"])])
    with pytest.raises(TaskGraphError):
        g.validate()


def test_ready_tasks_wait_for_done_dependencies():
    g = TaskGraph(
        [
            make_task("A", status="DONE"),
            make_task("B", deps=["A"]),
            make_task("C", deps=["B"]),
        ]
    )
    ready_ids = {t.id for t in g.ready_tasks()}
    assert ready_ids == {"B"}


def test_parallel_batches_split_non_overlapping_files():
    g = TaskGraph(
        [
            make_task("A", files=["src/backend/parser.py"]),
            make_task("B", files=["src/frontend/panel.tsx"]),
        ]
    )
    batches = g.parallelizable_batches()
    assert len(batches) == 1
    assert {t.id for t in batches[0]} == {"A", "B"}


def test_parallel_batches_keep_overlapping_files_apart():
    g = TaskGraph(
        [
            make_task("A", files=["src/humanitarian/geo.py"]),
            make_task("B", files=["src/humanitarian/"]),
        ]
    )
    batches = g.parallelizable_batches()
    assert len(batches) == 2


def test_tasks_without_files_hint_scheduled_alone():
    g = TaskGraph([make_task("A", files=[]), make_task("B", files=[])])
    batches = g.parallelizable_batches()
    assert len(batches) == 2


def test_overlap_is_detected_across_path_spellings():
    g = TaskGraph(
        [
            make_task("A", files=["./src/x.py"]),
            make_task("B", files=["src\\x.py"]),
        ]
    )
    assert len(g.parallelizable_batches()) == 2  # serialised
    assert g.likely_overlaps() == [("A", "B", "src/x.py")]


def test_likely_overlaps_reports_shared_files_not_disjoint_ones():
    g = TaskGraph(
        [
            make_task("SC-1", files=["apps/api/intel/x.py"]),
            make_task("SC-2", files=["apps/api/intel/x.py", "apps/api/intel/tests/"]),
            make_task("SC-3", files=["apps/web/panel.tsx"]),
        ]
    )
    pairs = g.likely_overlaps()
    assert ("SC-1", "SC-2", "apps/api/intel/x.py") in pairs
    assert not any("SC-3" in p for pair in pairs for p in pair)


def test_next_id_increments():
    g = TaskGraph([make_task("SC-001"), make_task("SC-002")])
    assert g.next_id("SC") == "SC-003"


def test_save_and_load_roundtrip(tmp_path):
    g = TaskGraph([make_task("A", deps=[]), make_task("B", deps=["A"])])
    path = tmp_path / "tasks.json"
    g.save(path)
    g2 = TaskGraph.load(path)
    assert {t.id for t in g2.all()} == {"A", "B"}
    assert g2.get("B").depends_on == ["A"]
