from conftest import init_repo
from orchestrator import engine, extensions, progress, state
from orchestrator.progress import register_console_progress
from orchestrator.task_graph import Task, TaskGraph
from orchestrator.workers.base import Worker, WorkerResponse


class OneShotWorker(Worker):
    name = "w"

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        return WorkerResponse(ok=True, summary="done", raw_output="", duration_seconds=0.01, worker=self.name)


def setup_function(fn):
    extensions.reset_extensions()
    progress._registered = False  # module-global guard; reset alongside the registry it guards


def teardown_function(fn):
    extensions.reset_extensions()
    progress._registered = False


def test_register_console_progress_prints_task_lifecycle(tmp_path, capsys):
    repo = init_repo(tmp_path / "demo")
    graph = TaskGraph(
        [Task(id="P-001", title="noop", status="READY", acceptance=["ok"], verification=["python -c \"1\""])]
    )
    state.save_task_store(repo, graph)

    register_console_progress()
    engine.run(repo=repo, prompt_text=None, implement_workers=[OneShotWorker()])

    out = capsys.readouterr().out
    assert "P-001" in out
    assert "implementing" in out
    assert "DONE" in out
    assert "finished:" in out


def test_register_console_progress_is_idempotent(tmp_path, capsys):
    repo = init_repo(tmp_path / "demo")
    graph = TaskGraph(
        [Task(id="P-002", title="noop", status="READY", acceptance=["ok"], verification=["python -c \"1\""])]
    )
    state.save_task_store(repo, graph)

    register_console_progress()
    register_console_progress()
    register_console_progress()
    engine.run(repo=repo, prompt_text=None, implement_workers=[OneShotWorker()])

    out = capsys.readouterr().out
    assert out.count("P-002: DONE") == 1
