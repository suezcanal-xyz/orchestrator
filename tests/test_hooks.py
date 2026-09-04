import threading

from conftest import init_repo

from orchestrator import engine, extensions, state
from orchestrator.task_graph import Task, TaskGraph
from orchestrator.workers.base import Worker, WorkerResponse


class OneShotWorker(Worker):
    def __init__(self, name, edit_fn=None):
        self.name = name
        self._edit_fn = edit_fn

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        if allow_edit and self._edit_fn:
            self._edit_fn(cwd)
        summary = "APPROVE" if "# Review task" in prompt else "done"
        return WorkerResponse(
            ok=True,
            summary=summary,
            raw_output=summary,
            duration_seconds=0.01,
            worker=self.name,
        )


def setup_function(fn):
    extensions.reset_extensions()


def teardown_function(fn):
    extensions.reset_extensions()


def test_run_fires_run_started_and_run_finished(tmp_path):
    repo = init_repo(tmp_path / "demo")
    graph = TaskGraph(
        [
            Task(
                id="H-001",
                title="noop",
                status="READY",
                acceptance=["ok"],
                verification=['python -c "1"'],
            )
        ]
    )
    state.save_task_store(repo, graph)

    events = []
    extensions.register_hook(
        "run_started", lambda **kw: events.append(("run_started", kw["task_ids"]))
    )
    extensions.register_hook(
        "run_finished",
        lambda **kw: events.append(("run_finished", kw["manifest"].status)),
    )

    engine.run(repo=repo, prompt_text=None, implement_workers=[OneShotWorker("w")])

    kinds = [e[0] for e in events]
    assert kinds == ["run_started", "run_finished"]
    assert events[0][1] == ["H-001"]


def test_task_lifecycle_hooks_fire_in_order(tmp_path):
    repo = init_repo(tmp_path / "demo")
    graph = TaskGraph(
        [
            Task(
                id="H-002",
                title="noop",
                status="READY",
                acceptance=["ok"],
                verification=['python -c "1"'],
            )
        ]
    )
    state.save_task_store(repo, graph)

    events = []
    lock = threading.Lock()
    for name in ("task_started", "task_implemented", "task_verified", "task_done"):
        extensions.register_hook(
            name,
            lambda _n=name, **kw: (lock.acquire(), events.append(_n), lock.release()),
        )

    engine.run(repo=repo, prompt_text=None, implement_workers=[OneShotWorker("w")])

    assert events == ["task_started", "task_implemented", "task_verified", "task_done"]


def test_task_blocked_and_debug_attempt_hooks_fire(tmp_path):
    repo = init_repo(
        tmp_path / "demo", files={"tests/t.py": "def test_x():\n    assert False\n"}
    )
    graph = TaskGraph(
        [
            Task(
                id="H-003",
                title="always fails",
                status="READY",
                acceptance=["ok"],
                verification=["python -m pytest tests/t.py -q"],
            )
        ]
    )
    state.save_task_store(repo, graph)

    events = []
    extensions.register_hook(
        "task_debug_attempt",
        lambda **kw: events.append(("attempt", kw["record"].attempt)),
    )
    extensions.register_hook(
        "task_blocked", lambda **kw: events.append(("blocked", kw["outcome"].task_id))
    )

    engine.run(
        repo=repo,
        prompt_text=None,
        implement_workers=[OneShotWorker("w")],
        max_debug_attempts=2,
    )

    attempts = [e for e in events if e[0] == "attempt"]
    assert [a[1] for a in attempts] == [1, 2]
    assert ("blocked", "H-003") in events


def test_hook_exception_does_not_break_run(tmp_path):
    repo = init_repo(tmp_path / "demo")
    graph = TaskGraph(
        [
            Task(
                id="H-004",
                title="noop",
                status="READY",
                acceptance=["ok"],
                verification=['python -c "1"'],
            )
        ]
    )
    state.save_task_store(repo, graph)

    def bad_hook(**kw):
        raise RuntimeError("boom")

    extensions.register_hook("task_started", bad_hook)

    result = engine.run(
        repo=repo, prompt_text=None, implement_workers=[OneShotWorker("w")]
    )
    assert result.task_outcomes[0].status == "DONE"
