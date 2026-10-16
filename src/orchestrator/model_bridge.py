"""Reproducible local/local and local/cloud coding-model comparisons.

An opt-in laboratory runner over existing workers. Never merges, pushes,
deploys, edits the source checkout or automatically changes worker policies.
Do not treat worktrees or OpenCode permissions as an OS sandbox.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import platform
import re
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import yaml

from orchestrator.verifier import run_verification
from orchestrator.workers.base import Worker, WorkerResponse
from orchestrator.workers.ollama import OllamaLocalWorker, validate_model
from orchestrator.workers.opencode import OpenCodeWorker

_ID = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
_CLOUD_MODEL = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:/-]+$")


class BridgeError(ValueError):
    """Invalid or unsafe evaluation request."""


@dataclass(frozen=True)
class Target:
    id: str
    kind: str
    model: str


@dataclass(frozen=True)
class Scenario:
    id: str
    prompt: str
    mode: str
    verification: tuple[str, ...] = ()


@dataclass(frozen=True)
class Suite:
    name: str
    scenarios: tuple[Scenario, ...]
    targets: tuple[Target, ...]
    repeats: int = 1
    timeout_seconds: int = 600
    verification_timeout_seconds: int = 120


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise BridgeError(f"{label} must match {_ID.pattern}")
    return value


def load_suite(path: Path) -> Suite:
    """Strict bounded input, no Python execution or YAML object construction."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise BridgeError("Suite must be a mapping with version: 1")
    name = _identifier(data.get("name"), "suite name")
    items = data.get("scenarios")
    targets = data.get("targets")
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise BridgeError("Provide 1 to 12 scenarios")
    if not isinstance(targets, list) or not 2 <= len(targets) <= 8:
        raise BridgeError("Provide 2 to 8 targets")
    scenarios = []
    for item in items:
        if not isinstance(item, dict):
            raise BridgeError("Each scenario must be a mapping")
        ident = _identifier(item.get("id"), "scenario id")
        prompt = item.get("prompt")
        mode = item.get("mode", "inspect")
        checks = item.get("verification", [])
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
            raise BridgeError(f"{ident}: prompt is empty or too long")
        if mode not in ("inspect", "patch"):
            raise BridgeError(f"{ident}: mode must be inspect or patch")
        if not isinstance(checks, list) or any(
            not isinstance(cmd, str) or not cmd.strip() or len(cmd) > 300
            for cmd in checks
        ):
            raise BridgeError(f"{ident}: invalid verification commands")
        if mode == "patch" and not checks:
            raise BridgeError(f"{ident}: patch scenarios require verification")
        scenarios.append(Scenario(ident, prompt, mode, tuple(checks)))
    parsed = []
    for item in targets:
        if not isinstance(item, dict):
            raise BridgeError("Each target must be a mapping")
        ident = _identifier(item.get("id"), "target id")
        kind, model = item.get("kind"), item.get("model")
        if kind not in ("local", "cloud") or not isinstance(model, str):
            raise BridgeError(f"{ident}: kind must be local/cloud with model string")
        if kind == "local":
            validate_model(model)
        elif not _CLOUD_MODEL.fullmatch(model) or model.startswith("ollama/"):
            raise BridgeError(f"{ident}: cloud model must be provider/model")
        parsed.append(Target(ident, kind, model))
    if len({x.id for x in scenarios}) != len(scenarios):
        raise BridgeError("Duplicate scenario IDs")
    if len({x.id for x in parsed}) != len(parsed):
        raise BridgeError("Duplicate target IDs")
    repeats = data.get("repeats", 1)
    timeout = data.get("timeout_seconds", 600)
    verify_timeout = data.get("verification_timeout_seconds", 120)
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise BridgeError("repeats must be an integer between 1 and 5")
    if type(timeout) is not int or not 30 <= timeout <= 3600:
        raise BridgeError("timeout_seconds must be 30..3600")
    if type(verify_timeout) is not int or not 5 <= verify_timeout <= 900:
        raise BridgeError("verification_timeout_seconds must be 5..900")
    return Suite(name, tuple(scenarios), tuple(parsed), repeats, timeout, verify_timeout)


def _permissions(*, edit: bool) -> dict:
    return {
        "*": "deny",
        "read": "allow",
        "glob": "allow",
        "grep": "allow",
        "lsp": "allow",
        "edit": "allow" if edit else "deny",
        "bash": "deny",
        "external_directory": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "task": "deny",
    }


def make_worker(target: Target, *, edit: bool) -> Worker:
    """Pin a single model/provider. No provider or model fallback."""
    if target.kind == "local":
        worker = OllamaLocalWorker(model=target.model)
        worker.edit_opt_in = edit
        return worker
    provider = target.model.split("/", 1)[0]
    permissions = _permissions(edit=edit)
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": target.model,
        "enabled_providers": [provider],
        "autoupdate": False,
        "share": "disabled",
        "permission": permissions,
        "agent": {
            "plan": {"permission": permissions},
            "build": {"permission": permissions},
        },
    }
    return OpenCodeWorker(
        model=target.model,
        agent="by-mode",
        config_content=json.dumps(config),
        auto_approve_edit=False,
    )


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
    )
    if proc.returncode:
        raise BridgeError(f"git {args[0]} failed: {proc.stderr[-400:]}")
    return proc.stdout.strip()


def _verify(checks: tuple[str, ...], path: Path, timeout: int) -> list[dict]:
    return [
        {"command": item.command, "passed": item.passed, "exit_code": item.exit_code,
         "duration_seconds": item.duration_seconds}
        for item in run_verification(list(checks), path, timeout_per_command=timeout)
    ]


def _summarize(records: list[dict], targets: tuple[Target, ...]) -> tuple[list[dict], list[dict]]:
    summaries = []
    for t in targets:
        rr = [r for r in records if r["target"] == t.id]
        scored = [r for r in rr if r["verdict"] in ("PASS", "FAIL", "ERROR")]
        passing = sum(r["verdict"] == "PASS" for r in scored)
        durations = [r["wall_seconds"] for r in rr if r["wall_seconds"] is not None]
        known_cost = [r["cost_usd"] for r in rr if r["cost_usd"] is not None]
        summaries.append({
            "target": t.id, "kind": t.kind, "model": t.model,
            "runs": len(rr), "scored_runs": len(scored),
            "passed": passing,
            "pass_rate": round(passing / len(scored), 4) if scored else None,
            "median_seconds": round(statistics.median(durations), 3) if durations else None,
            "reported_cost_usd": round(sum(known_cost), 6) if len(known_cost) == len(rr) and rr else None,
            "cost_coverage": f"{len(known_cost)}/{len(rr)}",
        })
    pairs = []
    for first, second in itertools.combinations(summaries, 2):
        kind = "local-local" if first["kind"] == second["kind"] == "local" else (
            "cloud-cloud" if first["kind"] == second["kind"] == "cloud" else "local-cloud"
        )
        pairs.append({
            "type": kind, "first": first["target"], "second": second["target"],
            "pass_rate_delta_first_minus_second": (
                round(first["pass_rate"] - second["pass_rate"], 4)
                if first["pass_rate"] is not None and second["pass_rate"] is not None
                else None
            ),
            "median_seconds_delta_first_minus_second": (
                round(first["median_seconds"] - second["median_seconds"], 3)
                if first["median_seconds"] is not None and second["median_seconds"] is not None
                else None
            ),
        })
    return summaries, pairs


def _markdown(report: dict) -> str:
    lines = [
        f"# Model bridge comparison: {report['suite']}",
        "",
        f"Repo commit: {report['source_commit']}  ",
        f"Suite SHA-256: {report['suite_sha256']}  ",
        f"Runs: {len(report['records'])}  ",
        "",
        "## Models",
        "",
        "| Target | Type | Tests passed | Pass rate | Median seconds | Reported USD |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for s in report["models"]:
        rate = "N/A" if s["pass_rate"] is None else f"{s['pass_rate']:.0%}"
        cost = "unknown" if s["reported_cost_usd"] is None else str(s["reported_cost_usd"])
        lines.append(
            f"| {s['target']} | {s['kind']} | {s['passed']}/{s['scored_runs']} | "
            f"{rate} | {s['median_seconds']} | {cost} |"
        )
    lines += ["", "## Pairwise comparison", ""]
    for p in report["pairs"]:
        lines.append(
            f"- {p['first']} vs {p['second']} ({p['type']}): "
            f"pass-rate delta {p['pass_rate_delta_first_minus_second']}, "
            f"median seconds delta {p['median_seconds_delta_first_minus_second']}"
        )
    lines += [
        "", "## Trial evidence", "",
        "| Scenario | Target | Trial | Status | Seconds | Verification |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for r in report["records"]:
        lines.append(
            f"| {r['scenario']} | {r['target']} | {r['trial']} | {r['verdict']} | "
            f"{r['wall_seconds']} | {r['verification']} |"
        )
    lines += [
        "", "## Limitations",
        "",
        "- PASS is based on declared tests and a recorded code change, not model self-report.",
        "- INSPECT_ONLY is unscored for correctness; do not treat it as a pass.",
        "- The baseline must fail before a bug-fix patch experiment is scored.",
        "- Unknown costs and unmeasured GPU/RAM/tokens are never set to zero.",
        "- This is not an OS sandbox; use a sanitized disposable checkout and restricted OS account.",
        "- Provider allowlisting does not prove network isolation; cloud requests require opt-in.",
        "- No run merges, deploys or changes production worker routing.",
        "",
    ]
    return "\n".join(lines)


def evaluate(
    repo: Path,
    suite_path: Path,
    output: Path,
    *,
    allow_cloud: bool = False,
    allow_edit: bool = False,
    confirmed_lab: bool = False,
    factory: Callable[..., Worker] = make_worker,
) -> dict:
    """Run fresh detached worktrees, save measured outcomes, never merge."""
    suite = load_suite(suite_path)
    repo = repo.resolve()
    output = output.resolve()
    if not confirmed_lab:
        raise BridgeError("Require --confirm-sanitized-lab for any execution")
    if any(t.kind == "cloud" for t in suite.targets) and not allow_cloud:
        raise BridgeError("Cloud targets require explicit --allow-cloud")
    if any(s.mode == "patch" for s in suite.scenarios) and not allow_edit:
        raise BridgeError("Patch scenarios require explicit --allow-edit")
    if not (repo / ".git").exists():
        raise BridgeError("Use a standalone sanitized Git clone, not a production worktree")
    if output == repo or repo in output.parents:
        raise BridgeError("Reports must be outside the case-study Git checkout")
    source_sha = _git(repo, "rev-parse", "HEAD")
    # Require no dirty source files; worktrees always start from this fixed SHA.
    if _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise BridgeError("Source clone must be clean, including untracked files")
    suite_digest = hashlib.sha256(suite_path.read_bytes()).hexdigest()
    if output.exists() and any(output.iterdir()):
        raise BridgeError("Output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="orchestrator-model-bridge-") as td:
        scratch = Path(td)
        for scenario in suite.scenarios:
            baseline_passed = None
            if scenario.mode == "patch":
                base_path = scratch / f"baseline-{scenario.id}"
                _git(repo, "worktree", "add", "--detach", str(base_path), source_sha)
                try:
                    baseline = _verify(
                        scenario.verification, base_path, suite.verification_timeout_seconds
                    )
                    baseline_passed = bool(baseline) and all(x["passed"] for x in baseline)
                finally:
                    _git(repo, "worktree", "remove", "--force", str(base_path))
            for trial in range(1, suite.repeats + 1):
                # Rotate order to reduce systematic warmed-cache advantages.
                order = list(suite.targets)
                order = order[(trial - 1) % len(order):] + order[:(trial - 1) % len(order)]
                for target in order:
                    record = {
                        "scenario": scenario.id, "target": target.id,
                        "kind": target.kind, "model": target.model,
                        "trial": trial, "mode": scenario.mode,
                        "verdict": "NOT_RUN", "baseline_passed": baseline_passed,
                        "wall_seconds": None, "worker_seconds": None,
                        "verification": "NOT_RUN", "checks": [],
                        "changed_files": [], "diff_sha256": None,
                        "cost_usd": None, "usage": None, "error": None,
                    }
                    if baseline_passed is True:
                        record["verdict"] = "INVALID_BASELINE"
                        records.append(record)
                        continue
                    wt = scratch / f"{scenario.id}-{target.id}-{trial}"
                    _git(repo, "worktree", "add", "--detach", str(wt), source_sha)
                    started = time.monotonic()
                    try:
                        worker = factory(target, edit=scenario.mode == "patch")
                        prompt = (
                            "You are evaluating an isolated benchmark task. "
                            "No network access, no git push/commit, no production services. "
                            "Do not alter test expectations or verification files. "
                            "Use only the current disposable working tree.\n\n"
                            f"Task: {scenario.prompt}\n\n"
                            f"Acceptance checks (run independently afterwards): "
                            f"{list(scenario.verification)}"
                        )
                        response: WorkerResponse = worker._invoke(
                            wt, prompt, timeout=suite.timeout_seconds,
                            allow_edit=scenario.mode == "patch",
                        )
                        record["worker_seconds"] = response.duration_seconds
                        record["cost_usd"] = response.cost_usd
                        record["usage"] = response.extra.get("usage") or None
                        if not response.ok:
                            record["verdict"] = "ERROR"
                            record["error"] = response.error or "worker failed"
                        elif scenario.mode == "inspect":
                            record["verdict"] = "INSPECT_ONLY"
                            record["verification"] = "NOT_APPLICABLE"
                        else:
                            record["checks"] = _verify(
                                scenario.verification, wt, suite.verification_timeout_seconds
                            )
                            record["verification"] = (
                                "PASS" if all(v["passed"] for v in record["checks"]) else "FAIL"
                            )
                            record["verdict"] = record["verification"]
                        record["changed_files"] = _git(
                            wt, "status", "--porcelain", "--untracked-files=all"
                        ).splitlines()
                        diff = _git(wt, "diff", "--binary", "HEAD")
                        if diff:
                            record["diff_sha256"] = hashlib.sha256(
                                diff.encode("utf-8")
                            ).hexdigest()
                            (output / f"{scenario.id}-{target.id}-{trial}.diff").write_text(
                                diff + "\n", encoding="utf-8"
                            )
                        if scenario.mode == "patch" and record["verdict"] == "PASS":
                            if not record["changed_files"]:
                                record["verdict"] = "FAIL"
                                record["verification"] = "NO_CHANGE"
                    except Exception as exc:
                        record["verdict"] = "ERROR"
                        record["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                    finally:
                        record["wall_seconds"] = round(time.monotonic() - started, 3)
                        _git(repo, "worktree", "remove", "--force", str(wt))
                        records.append(record)
    models, pairs = _summarize(records, suite.targets)
    report = {
        "schema": "org.suezcanal.orchestrator.model-bridge/v1",
        "suite": suite.name,
        "created_at": datetime.now(UTC).isoformat(),
        "source_commit": source_sha,
        "suite_sha256": suite_digest,
        "platform": {"system": platform.system(), "release": platform.release(),
                     "python": platform.python_version(), "machine": platform.machine()},
        "permissions": {"cloud_authorized": allow_cloud, "edit_authorized": allow_edit,
                        "sanitized_lab_confirmed": confirmed_lab},
        "records": records, "models": models, "pairs": pairs,
    }
    (output / "comparison.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "comparison.md").write_text(_markdown(report), encoding="utf-8")
    return report
