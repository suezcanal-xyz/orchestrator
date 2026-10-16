"""Deterministic model bridge tests: no LLM, network or production dependency."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from orchestrator.cli import main
from orchestrator.model_bridge import BridgeError, evaluate, load_suite, make_worker
from orchestrator.workers.base import Worker, WorkerResponse


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _demo(tmp_path: Path) -> Path:
    repo = tmp_path / "seacommons-lab"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-b", "main")
    (repo / "ais_rules.py").write_text(
        "def is_excluded_ship_type(value):\n    return value == 37\n",
        encoding="utf-8",
    )
    (repo / "test_regression.py").write_text(
        "import unittest\n"
        "from ais_rules import is_excluded_ship_type\n"
        "class TestRules(unittest.TestCase):\n"
        "    def test_passenger(self):\n"
        "        self.assertTrue(is_excluded_ship_type(65))\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=Bridge",
        "-c",
        "user.email=bridge@example.test",
        "commit",
        "-m",
        "known red baseline",
    )
    return repo


def _suite(path: Path, *, cloud: bool = False, mode: str = "patch") -> Path:
    targets = [
        "  - id: qwen-coder\n    kind: local\n    model: qwen2.5-coder:3b",
        "  - id: qwen-general\n    kind: local\n    model: qwen3:4b",
    ]
    if cloud:
        targets.append(
            "  - id: provider-cloud\n    kind: cloud\n    model: anthropic/claude-test"
        )
    suite_path = path / "suite.yaml"
    suite_path.write_text(
        "version: 1\n"
        "name: seacommons-ais\n"
        "repeats: 2\n"
        "timeout_seconds: 60\n"
        "verification_timeout_seconds: 20\n"
        "scenarios:\n"
        "  - id: exclude-passengers\n"
        f"    mode: {mode}\n"
        "    prompt: Correct the AIS passenger type check without editing tests.\n"
        + (
            "    verification:\n      - python -m unittest -q test_regression.py\n"
            "    allowed_paths:\n      - ais_rules.py\n"
            if mode == "patch"
            else ""
        )
        + "targets:\n"
        + "\n".join(targets)
        + "\n",
        encoding="utf-8",
    )
    return suite_path


class FakeAgent(Worker):
    name = "fake"

    def __init__(self, target):
        self.target = target

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        if allow_edit and self.target.id != "qwen-general":
            (cwd / "ais_rules.py").write_text(
                "def is_excluded_ship_type(value):\n"
                "    return value == 37 or 60 <= value <= 69\n",
                encoding="utf-8",
            )
        return WorkerResponse(
            ok=True,
            summary="proposed change",
            raw_output="",
            duration_seconds=1.0,
            worker=self.target.id,
            cost_usd=0.001 if self.target.kind == "cloud" else None,
        )


def factory(target, *, edit):
    return FakeAgent(target)


def test_real_isolated_trials_and_comparable_reports(tmp_path):
    repo = _demo(tmp_path)
    suite = _suite(tmp_path)
    out = tmp_path / "reports"
    before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).strip()
    result = evaluate(
        repo, suite, out, confirmed_lab=True, allow_edit=True, factory=factory
    )
    assert len(result["records"]) == 4
    assert {p["type"] for p in result["pairs"]} == {"local-local"}
    assert sum(r["verdict"] == "PASS" for r in result["records"]) == 2
    assert sum(r["verdict"] == "FAIL" for r in result["records"]) == 2
    assert result["models"][0]["reported_cost_usd"] is None
    assert (out / "comparison.json").exists()
    assert "local-local" in (out / "comparison.md").read_text(encoding="utf-8")
    assert (out / "exclude-passengers-qwen-coder-1.diff").exists()
    assert (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).strip()
        == before
    )
    assert not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repo
    ).strip()
    worktrees = subprocess.check_output(
        ["git", "worktree", "list", "--porcelain"], cwd=repo
    ).decode()
    assert worktrees.count("worktree ") == 1


def test_hybrid_requires_cloud_authorization_and_has_pairwise_report(tmp_path):
    repo = _demo(tmp_path)
    suite = _suite(tmp_path, cloud=True)
    with pytest.raises(BridgeError, match="allow-cloud"):
        evaluate(
            repo,
            suite,
            tmp_path / "nope",
            confirmed_lab=True,
            allow_edit=True,
            factory=factory,
        )
    result = evaluate(
        repo,
        suite,
        tmp_path / "hybrid",
        confirmed_lab=True,
        allow_edit=True,
        allow_cloud=True,
        factory=factory,
    )
    assert len(result["records"]) == 6
    assert {p["type"] for p in result["pairs"]} == {"local-local", "local-cloud"}
    cloud = next(m for m in result["models"] if m["kind"] == "cloud")
    assert cloud["reported_cost_usd"] == 0.002


def test_inspect_cannot_be_scored_as_correct(tmp_path):
    repo = _demo(tmp_path)
    suite = _suite(tmp_path, mode="inspect")
    result = evaluate(
        repo, suite, tmp_path / "inspect", confirmed_lab=True, factory=factory
    )
    assert all(r["verdict"] == "INSPECT_ONLY" for r in result["records"])
    assert all(m["pass_rate"] is None for m in result["models"])


def test_cli_requires_explicit_lab_and_edit_authorizations(tmp_path):
    repo = _demo(tmp_path)
    suite = _suite(tmp_path)
    r = CliRunner().invoke(
        main, ["compare", str(repo), str(suite), "--output", str(tmp_path / "out")]
    )
    assert r.exit_code != 0
    assert "confirm-sanitized-lab" in r.output
    r = CliRunner().invoke(
        main,
        [
            "compare",
            str(repo),
            str(suite),
            "--output",
            str(tmp_path / "out"),
            "--confirm-sanitized-lab",
        ],
    )
    assert r.exit_code != 0
    assert "allow-edit" in r.output


def test_invalid_model_and_duplicate_ids(tmp_path):
    suite = _suite(tmp_path)
    data = suite.read_text(encoding="utf-8").replace("qwen3:4b", "qwen3:4b-cloud")
    suite.write_text(data, encoding="utf-8")
    with pytest.raises(ValueError, match="Cloud"):
        load_suite(suite)
    suite.write_text(
        data.replace("qwen3:4b-cloud", "qwen2.5-coder:3b").replace(
            "id: qwen-general", "id: qwen-coder"
        ),
        encoding="utf-8",
    )
    with pytest.raises(BridgeError, match="Duplicate target"):
        load_suite(suite)


def test_readonly_cloud_model_provider_pinned():
    from orchestrator.model_bridge import Target

    cloud = make_worker(
        Target("provider-cloud", "cloud", "anthropic/claude-test"), edit=False
    )
    config = json.loads(cloud.config_content)
    assert config["enabled_providers"] == ["anthropic"]
    assert config["permission"]["edit"] == "deny"
    assert config["permission"]["bash"] == "deny"
    assert config["model"] == "anthropic/claude-test"


def test_dirty_lab_refused(tmp_path):
    repo = _demo(tmp_path)
    (repo / "personal-token.env").write_text("SECRET=fake", encoding="utf-8")
    with pytest.raises(BridgeError, match="clean"):
        evaluate(
            repo,
            _suite(tmp_path),
            tmp_path / "out",
            confirmed_lab=True,
            allow_edit=True,
            factory=factory,
        )


def test_green_baseline_is_not_counted_as_agent_success(tmp_path):
    repo = _demo(tmp_path)
    (repo / "ais_rules.py").write_text(
        "def is_excluded_ship_type(value):\n"
        "    return value == 37 or 60 <= value <= 69\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=Bridge",
        "-c",
        "user.email=bridge@example.test",
        "commit",
        "-m",
        "baseline already green",
    )
    result = evaluate(
        repo,
        _suite(tmp_path),
        tmp_path / "out",
        confirmed_lab=True,
        allow_edit=True,
        factory=factory,
    )
    assert all(r["verdict"] == "INVALID_BASELINE" for r in result["records"])
    assert all(m["pass_rate"] is None for m in result["models"])


def test_benchmark_rejects_test_tampering_even_when_tests_go_green(tmp_path):
    repo = _demo(tmp_path)
    suite = _suite(tmp_path)

    class Tamper(FakeAgent):
        def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
            result = super()._invoke(
                cwd, prompt, timeout=timeout, allow_edit=allow_edit,
                structured=structured,
            )
            (cwd / "test_regression.py").write_text(
                "import unittest\nclass TestRules(unittest.TestCase):\n"
                "    def test_passenger(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            return result

    result = evaluate(
        repo, suite, tmp_path / "tamper",
        confirmed_lab=True, allow_edit=True,
        factory=lambda target, edit: Tamper(target),
    )
    assert all(r["verdict"] == "POLICY_VIOLATION" for r in result["records"])
    assert all(m["pass_rate"] == 0 for m in result["models"])


def test_missing_verifier_is_not_a_valid_red_baseline(tmp_path):
    repo = _demo(tmp_path)
    suite = _suite(tmp_path)
    suite.write_text(
        suite.read_text(encoding="utf-8").replace(
            "python -m unittest -q test_regression.py",
            "missing-executable-xyz --version",
        ),
        encoding="utf-8",
    )
    report = evaluate(
        repo, suite, tmp_path / "missing-verifier",
        confirmed_lab=True, allow_edit=True, factory=factory,
    )
    assert all(r["verdict"] == "BASELINE_ERROR" for r in report["records"])
    assert all(m["pass_rate"] is None for m in report["models"])
