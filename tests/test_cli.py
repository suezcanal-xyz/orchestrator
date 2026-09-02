import json

from click.testing import CliRunner

from conftest import init_repo
from orchestrator import extensions
from orchestrator.cli import main
from orchestrator.workers.base import Worker, WorkerResponse


class FakeReconcileWorker(Worker):
    name = "fakecli"

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        payload = json.dumps(
            {
                "classification": "NEW_REQUIREMENT",
                "change_history_entry": "Added via CLI test.",
                "tasks": [
                    {
                        "title": "Do the thing",
                        "acceptance": ["it works"],
                        "verification": ["python -c \"1\""],
                        "priority": "P2",
                        "files_hint": [],
                    }
                ],
            }
        )
        return WorkerResponse(ok=True, summary=payload, raw_output=payload, duration_seconds=0.01, worker=self.name)


def setup_module(module):
    extensions.register_worker("fakecli", FakeReconcileWorker)


def teardown_module(module):
    extensions.reset_extensions()


def test_inspect_command(tmp_path):
    repo = init_repo(tmp_path / "demo")
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(repo)])
    assert result.exit_code == 0
    assert "Repository context" in result.output


def test_ingest_then_plan_then_status(tmp_path):
    repo = init_repo(tmp_path / "demo")
    runner = CliRunner()

    r1 = runner.invoke(main, ["ingest", str(repo), "please add the thing", "--worker", "fakecli"])
    assert r1.exit_code == 0, r1.output
    assert "classification: NEW_REQUIREMENT" in r1.output
    assert "added tasks:" in r1.output

    r2 = runner.invoke(main, ["plan", str(repo)])
    assert r2.exit_code == 0
    assert "Do the thing" in r2.output

    r3 = runner.invoke(main, ["status", str(repo), "--json"])
    assert r3.exit_code == 0
    data = json.loads(r3.output)
    assert data["total_tasks"] == 1


def test_plan_before_ingest_errors_clearly(tmp_path):
    repo = init_repo(tmp_path / "demo")
    runner = CliRunner()
    result = runner.invoke(main, ["plan", str(repo)])
    assert result.exit_code != 0
    assert "ingest" in result.output


def test_unknown_worker_errors_clearly(tmp_path):
    repo = init_repo(tmp_path / "demo")
    runner = CliRunner()
    result = runner.invoke(main, ["ingest", str(repo), "x", "--worker", "nope"])
    assert result.exit_code != 0
    assert "unknown worker" in result.output


def test_init_scaffolds_and_refuses_overwrite(tmp_path):
    repo = init_repo(tmp_path / "demo")
    runner = CliRunner()

    r1 = runner.invoke(main, ["init", str(repo), "--project", "demo"])
    assert r1.exit_code == 0, r1.output
    assert "created  docs/PLAN.md" in r1.output
    assert (repo / "docs" / "PLAN.md").exists()
    assert (repo / "AGENTS.md").exists()

    r2 = runner.invoke(main, ["init", str(repo)])
    assert r2.exit_code == 0
    assert "skipped  docs/PLAN.md" in r2.output


def test_onboarding_help_works_without_the_extra():
    runner = CliRunner()
    result = runner.invoke(main, ["onboarding", "--help"])
    assert result.exit_code == 0
    assert "dashboard" in result.output
