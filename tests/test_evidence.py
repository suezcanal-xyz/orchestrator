import subprocess

from orchestrator import evidence, state
from orchestrator.workers.base import WorkerResponse


def _repo(tmp_path):
    p = tmp_path / "repo"
    p.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
    (p / ".gitignore").write_text("", encoding="utf-8")
    return p


def test_run_usage_summary_aggregates_by_worker_and_stage(tmp_path):
    rp = state.init_run(_repo(tmp_path))

    evidence.save_worker_response(
        rp, "T-1", "implement",
        WorkerResponse(True, "s", "", 1.0, "claude", cost_usd=0.05,
                       extra={"usage": {"input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 50, "cost_usd": 0.05}}),
    )
    evidence.save_worker_response(
        rp, "T-1", "debug-1",
        WorkerResponse(True, "s", "", 1.0, "codex", cost_usd=0.02,
                       extra={"usage": {"input_tokens": 0, "output_tokens": 500, "cache_read_tokens": 0}}),
    )
    evidence.save_worker_response(
        rp, "T-2", "implement",
        WorkerResponse(True, "s", "", 1.0, "claude", cost_usd=0.03,
                       extra={"usage": {"input_tokens": 800, "output_tokens": 100, "cache_read_tokens": 0, "cost_usd": 0.03}}),
    )

    summary = evidence.run_usage_summary(rp)
    assert summary["totals"]["cost_usd"] == 0.10
    assert summary["totals"]["input_tokens"] == 1800
    assert summary["totals"]["output_tokens"] == 800
    assert summary["by_worker"]["claude"]["cost_usd"] == 0.08
    assert summary["by_worker"]["codex"]["output_tokens"] == 500
    # debug-1 folded into "debug"
    assert "debug" in summary["by_stage"]
    assert summary["by_stage"]["implement"]["input_tokens"] == 1800


def test_run_usage_summary_empty_run(tmp_path):
    rp = state.init_run(_repo(tmp_path))
    summary = evidence.run_usage_summary(rp)
    assert summary["totals"]["cost_usd"] == 0.0
    assert summary["by_worker"] == {}


def test_format_cost_section_renders_total_and_breakdown(tmp_path):
    rp = state.init_run(_repo(tmp_path))
    evidence.save_worker_response(
        rp, "T-1", "implement",
        WorkerResponse(True, "s", "", 1.0, "opencode", cost_usd=0.123,
                       extra={"usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_tokens": 0}}),
    )
    section = evidence.format_cost_section(evidence.run_usage_summary(rp))
    assert "## Cost" in section
    assert "$0.1230" in section
    assert "opencode" in section
