import subprocess

from orchestrator import evidence, state
from orchestrator.task_graph import Task, TaskGraph
from orchestrator.verifier import VerificationResult
from orchestrator.workers.base import WorkerResponse


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)
    return path


def test_ensure_gitignore_appends_once(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    state.ensure_gitignore(repo)
    state.ensure_gitignore(repo)  # idempotent
    content = (repo / ".gitignore").read_text(encoding="utf-8")
    assert content.count(".orchestrator/") == 1


def test_ensure_gitignore_preserves_existing_content(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    state.ensure_gitignore(repo)
    content = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "node_modules/" in content
    assert ".orchestrator/" in content


def test_init_run_creates_expected_tree(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    rp = state.init_run(repo, run_id="run-test-1")
    assert rp.evidence_dir.is_dir()
    assert rp.logs_dir.is_dir()
    assert rp.diffs_dir.is_dir()
    assert rp.tests_dir.is_dir()
    assert rp.root == repo / ".orchestrator" / "runs" / "run-test-1"


def test_task_store_roundtrip(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    graph = TaskGraph([Task(id="SC-001", title="x", acceptance=["a"], verification=["v"])])
    state.save_task_store(repo, graph)
    loaded = state.load_task_store(repo)
    assert loaded.get("SC-001").title == "x"


def test_load_task_store_missing_is_empty(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    assert len(state.load_task_store(repo)) == 0


def test_run_manifest_roundtrip(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    rp = state.init_run(repo, run_id="run-test-2")
    m = state.RunManifest(
        run_id="run-test-2",
        repo=str(repo),
        prompt="fix humanitarian",
        started_at=state.now_iso(),
        protected_branch="main",
        status="IN_PROGRESS",
        task_ids=["SC-001"],
    )
    m.save(rp)
    loaded = state.RunManifest.load(rp)
    assert loaded.prompt == "fix humanitarian"
    assert loaded.task_ids == ["SC-001"]


def test_evidence_writers(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    rp = state.init_run(repo, run_id="run-test-3")

    evidence.save_diff(rp, "SC-001", "diff --git a b\n")
    assert (rp.diffs_dir / "SC-001.diff").exists()

    evidence.save_log(rp, "SC-001", "implement", "hello log line")
    log_text = (rp.logs_dir / "SC-001.implement.log").read_text(encoding="utf-8")
    assert "hello log line" in log_text

    resp = WorkerResponse(ok=True, summary="done", raw_output="x" * 30000, duration_seconds=1.2, worker="claude")
    path = evidence.save_worker_response(rp, "SC-001", "implement", resp)
    assert path.exists()
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["summary"] == "done"
    assert len(data["raw_output_truncated"]) <= evidence.MAX_RAW_OUTPUT_CHARS

    results = [VerificationResult(command="pytest", exit_code=0, passed=True)]
    evidence.save_verification(rp, "SC-001", results)
    saved = json.loads((rp.tests_dir / "SC-001.json").read_text(encoding="utf-8"))
    assert saved[0]["command"] == "pytest"

    evidence.write_verdict(rp, "# VERDICT\n\nREADY FOR REVIEW\n")
    assert "READY FOR REVIEW" in rp.verdict.read_text(encoding="utf-8")
