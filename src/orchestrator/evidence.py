"""Evidence-writing helpers for a run's audit trail (spec section 14).

Everything here writes into a RunPaths tree produced by state.init_run().
No decisions are made in this module -- it only serializes what already
happened (a worker response, a verification result, a diff) so that a
human can later reconstruct what was requested, what changed, what failed,
and why the milestone was or was not reached.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.state import RunPaths
    from orchestrator.verifier import VerificationResult
    from orchestrator.workers.base import WorkerResponse

MAX_RAW_OUTPUT_CHARS = 20_000


def save_diff(run_paths: "RunPaths", task_id: str, diff_text: str) -> Path:
    path = run_paths.diffs_dir / f"{task_id}.diff"
    path.write_text(diff_text, encoding="utf-8")
    return path


def save_log(run_paths: "RunPaths", task_id: str, stage: str, text: str) -> Path:
    path = run_paths.logs_dir / f"{task_id}.{stage}.log"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing + text.rstrip() + "\n", encoding="utf-8")
    return path


def save_worker_response(run_paths: "RunPaths", task_id: str, stage: str, response: "WorkerResponse") -> Path:
    path = run_paths.evidence_dir / f"{task_id}.{stage}.json"
    data = {
        "task_id": task_id,
        "stage": stage,
        "worker": response.worker,
        "ok": response.ok,
        "summary": response.summary,
        "duration_seconds": response.duration_seconds,
        "session_id": response.session_id,
        "cost_usd": response.cost_usd,
        "error": response.error,
        "extra": response.extra,
        "raw_output_truncated": response.raw_output[-MAX_RAW_OUTPUT_CHARS:],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def save_verification(run_paths: "RunPaths", task_id: str, results: list["VerificationResult"]) -> Path:
    path = run_paths.tests_dir / f"{task_id}.json"
    existing: list[dict] = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    existing.extend(r.to_dict() for r in results)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_verdict(run_paths: "RunPaths", verdict_text: str) -> Path:
    run_paths.verdict.write_text(verdict_text, encoding="utf-8")
    return run_paths.verdict
