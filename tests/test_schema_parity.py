import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.state import RunManifest
from orchestrator.task_graph import Task
from orchestrator.verifier import VerificationResult

ROOT = Path(__file__).parents[1]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def test_task_schema_accepts_a_runtime_opencode_task():
    task = Task(
        id="PUB-001",
        title="Use OpenCode",
        acceptance=["worker is recorded"],
        verification=["python -m pytest -q"],
        worker="opencode",
    )
    jsonschema.validate(task.to_dict(), _schema("task.schema.json"))


@pytest.mark.parametrize("status", ["BLOCKED_SESSION_LIMIT", "SCOPED_OK", "NO_WORK"])
def test_run_schema_accepts_all_runtime_run_statuses(status: str):
    manifest = RunManifest(
        run_id="run-p0",
        repo="example",
        prompt="continue",
        started_at="2026-09-04T00:00:00+00:00",
        protected_branch="main",
        status=status,
        resumed_from="run-before",
    )
    jsonschema.validate(manifest.to_dict(), _schema("run.schema.json"))


def test_result_schema_accepts_runtime_verification_result():
    result = VerificationResult(command="python -m pytest -q", exit_code=0, passed=True)
    jsonschema.validate(result.to_dict(), _schema("result.schema.json"))
