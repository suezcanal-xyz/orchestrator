import json

import pytest

from orchestrator import plan as plan_mod
from orchestrator.reconcile import ReconciliationError, derive_prefix, reconcile
from orchestrator.task_graph import Task, TaskGraph
from orchestrator.workers.base import Worker, WorkerResponse


class FakeReconcileWorker(Worker):
    name = "fake"

    def __init__(self, summaries: list[str]):
        self._summaries = summaries
        self._calls = 0

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        s = self._summaries[min(self._calls, len(self._summaries) - 1)]
        self._calls += 1
        return WorkerResponse(ok=True, summary=s, raw_output=s, duration_seconds=0.01, worker=self.name)


VALID_PAYLOAD = json.dumps(
    {
        "classification": "BUG",
        "change_history_entry": "NGO vessel panel drops entries reported by inspection.",
        "tasks": [
            {
                "title": "Fix NGO vessel panel dropping entries",
                "acceptance": ["all 14 vessels visible"],
                "verification": ["pytest tests/humanitarian"],
                "priority": "P1",
                "files_hint": ["src/humanitarian/panel.py"],
            }
        ],
    }
)


def test_derive_prefix_camel_case():
    assert derive_prefix("SeaCommons") == "SC"


def test_derive_prefix_single_word():
    assert derive_prefix("republic") == "REPU"


def test_reconcile_adds_task_and_change_history(tmp_path):
    doc = plan_mod.new_plan("SeaCommons")
    graph = TaskGraph()
    worker = FakeReconcileWorker([VALID_PAYLOAD])

    result = reconcile(
        cwd=tmp_path,
        prompt_text="NGO panel is missing vessels",
        plan=doc,
        graph=graph,
        context_block="(context)",
        worker=worker,
    )

    assert result.classification == "BUG"
    assert len(result.added_task_ids) == 1
    task_id = result.added_task_ids[0]
    assert task_id.startswith("SC-")
    assert graph.get(task_id).title == "Fix NGO vessel panel dropping entries"
    assert "NGO vessel panel drops entries" in doc.get_section("Change History")
    assert task_id in doc.get_section("Tasks")


def test_reconcile_skips_duplicate_active_task(tmp_path):
    doc = plan_mod.new_plan("SeaCommons")
    graph = TaskGraph([
        Task(
            id="SC-001",
            title="Fix NGO vessel panel dropping entries",
            status="READY",
            acceptance=["x"],
            verification=["y"],
        )
    ])
    worker = FakeReconcileWorker([VALID_PAYLOAD])

    result = reconcile(
        cwd=tmp_path,
        prompt_text="NGO panel is missing vessels",
        plan=doc,
        graph=graph,
        context_block="(context)",
        worker=worker,
    )

    assert result.added_task_ids == []
    assert result.skipped_duplicates == ["Fix NGO vessel panel dropping entries"]
    assert len(graph) == 1


def test_reconcile_parses_fenced_json():
    from orchestrator.reconcile import _extract_json

    fenced = "```json\n" + VALID_PAYLOAD + "\n```"
    data = _extract_json(fenced)
    assert data["classification"] == "BUG"


def test_reconcile_retries_once_then_succeeds(tmp_path):
    doc = plan_mod.new_plan("SeaCommons")
    graph = TaskGraph()
    worker = FakeReconcileWorker(["not json at all", VALID_PAYLOAD])

    result = reconcile(
        cwd=tmp_path,
        prompt_text="NGO panel is missing vessels",
        plan=doc,
        graph=graph,
        context_block="(context)",
        worker=worker,
        max_retries=1,
    )
    assert result.classification == "BUG"
    assert len(result.added_task_ids) == 1


def test_reconcile_raises_after_exhausting_retries(tmp_path):
    doc = plan_mod.new_plan("SeaCommons")
    graph = TaskGraph()
    worker = FakeReconcileWorker(["still not json", "nope"])

    with pytest.raises(ReconciliationError):
        reconcile(
            cwd=tmp_path,
            prompt_text="NGO panel is missing vessels",
            plan=doc,
            graph=graph,
            context_block="(context)",
            worker=worker,
            max_retries=1,
        )
