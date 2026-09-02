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


_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens")


def run_usage_summary(run_paths: "RunPaths") -> dict:
    """Aggregate every `<task>.<stage>.json` worker-response file in this run
    into cost + token totals, broken down by worker and by stage.

    `stage` is the part after the last dot before `.json` with any trailing
    `-<n>` (debug-1, debug-2) folded into `debug`.
    """
    totals = {"cost_usd": 0.0, **{k: 0 for k in _USAGE_KEYS}}
    by_worker: dict[str, dict] = {}
    by_stage: dict[str, dict] = {}

    for path in sorted(run_paths.evidence_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        worker = data.get("worker") or "unknown"
        stem_parts = path.stem.split(".")
        stage = stem_parts[-1] if len(stem_parts) > 1 else "unknown"
        stage = stage.split("-")[0]  # debug-1 -> debug

        usage = (data.get("extra") or {}).get("usage") or {}
        cost = data.get("cost_usd")
        if cost is None:
            cost = usage.get("cost_usd", 0.0) or 0.0

        for bucket, key in ((by_worker, worker), (by_stage, stage)):
            slot = bucket.setdefault(key, {"cost_usd": 0.0, **{k: 0 for k in _USAGE_KEYS}})
            slot["cost_usd"] += float(cost)
            for k in _USAGE_KEYS:
                slot[k] += int(usage.get(k, 0) or 0)
        totals["cost_usd"] += float(cost)
        for k in _USAGE_KEYS:
            totals[k] += int(usage.get(k, 0) or 0)

    return {"totals": totals, "by_worker": by_worker, "by_stage": by_stage}


def format_cost_section(summary: dict) -> str:
    t = summary["totals"]
    lines = ["## Cost", "", f"Total: ${t['cost_usd']:.4f}"]
    tok = t["input_tokens"] + t["output_tokens"]
    if tok:
        lines.append(
            f"Tokens: {tok:,} ({t['input_tokens']:,} in / {t['output_tokens']:,} out"
            + (f" / {t['cache_read_tokens']:,} cache-read" if t["cache_read_tokens"] else "")
            + ")"
        )
    if summary["by_worker"]:
        lines += ["", "By worker:"]
        for w, s in sorted(summary["by_worker"].items()):
            lines.append(f"  {w}: ${s['cost_usd']:.4f}  ({s['input_tokens'] + s['output_tokens']:,} tok)")
    if summary["by_stage"]:
        lines += ["", "By stage:"]
        for st, s in sorted(summary["by_stage"].items()):
            lines.append(f"  {st}: ${s['cost_usd']:.4f}  ({s['input_tokens'] + s['output_tokens']:,} tok)")
    lines.append("")
    return "\n".join(lines)
