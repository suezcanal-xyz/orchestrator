"""FastAPI backend for `orchestrator onboarding`.

Localhost-only, single user, no auth layer (see docs/ONBOARDING.md -- it
must not be exposed). Every mutating route maps to something the CLI
already does:

    /api/doctor  -> orchestrator.doctor.run_doctor
    /api/login   -> spawns `codex login` / `claude auth login` / `opencode auth login`
    /api/repo    -> orchestrator.engine.status
    /api/init    -> orchestrator.scaffold.scaffold_repo
    /api/run     -> orchestrator.engine.run  (background thread)
    /api/events  -> Server-Sent Events, fed by orchestrator.extensions hooks
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

from orchestrator import engine, extensions
from orchestrator.doctor import run_doctor

LOGIN_COMMANDS: dict[str, list[str]] = {
    "codex": ["codex", "login"],
    "claude": ["claude", "auth", "login"],
    "opencode": ["opencode", "auth", "login"],
}

# One in-process event bus. The dashboard is single-user; a run at a time.
_events: "queue.Queue[dict]" = queue.Queue()
_run_lock = threading.Lock()
_run_active = threading.Event()


def _publish(event: str, payload: dict) -> None:
    _events.put({"event": event, **payload})


def _register_dashboard_hooks() -> None:
    if getattr(_register_dashboard_hooks, "_done", False):
        return

    def mk(name):
        def handler(**kw):
            safe = {}
            for k, v in kw.items():
                try:
                    json.dumps(v)
                    safe[k] = v
                except (TypeError, ValueError):
                    safe[k] = _describe(v)
            _publish(name, safe)

        return handler

    for evt in (
        "reconcile_done", "run_started", "task_started", "task_implemented",
        "task_verified", "task_debug_attempt", "task_done", "task_blocked", "run_finished",
    ):
        extensions.register_hook(evt, mk(evt))
    _register_dashboard_hooks._done = True


def _describe(v) -> str:
    for attr in ("id", "task_id", "run_id", "status", "classification"):
        if hasattr(v, attr):
            return f"{type(v).__name__}({attr}={getattr(v, attr)!r})"
    return type(v).__name__


def _spawn_login(worker: str) -> None:
    cmd = LOGIN_COMMANDS[worker]
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)  # noqa: S603 - fixed command, no shell


def _run_engine(repo: Path, prompt: str | None, workers: list[str]) -> None:
    from orchestrator.cli import _resolve_workers

    try:
        resolved = _resolve_workers(tuple(workers))
        result = engine.run(repo=repo, prompt_text=prompt, implement_workers=resolved)
        _publish("done", {
            "status": result.verdict.result_status.value if result.verdict else "UNKNOWN",
            "verdict": result.run_paths.verdict.read_text(encoding="utf-8"),
            "usage": result.usage,
            "run_dir": str(result.run_paths.root),
        })
    except Exception as e:  # noqa: BLE001 - report to the page, don't crash the server
        _publish("error", {"message": f"{type(e).__name__}: {e}"})
    finally:
        _run_active.clear()


def create_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, StreamingResponse

    _register_dashboard_hooks()
    app = FastAPI(title="orchestrator onboarding")
    static = Path(__file__).parent / "static"

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (static / "index.html").read_text(encoding="utf-8")

    @app.get("/api/doctor")
    def doctor() -> list[dict]:
        out = []
        for e in run_doctor():
            out.append({
                "name": e.name, "found": e.found, "path": e.path,
                "worker_registered": e.worker_registered, "auth_note": e.auth_note,
            })
        return out

    @app.post("/api/login/{worker}")
    def login(worker: str) -> dict:
        if worker not in LOGIN_COMMANDS:
            raise HTTPException(400, f"unknown worker {worker!r}")
        _spawn_login(worker)
        return {"started": " ".join(LOGIN_COMMANDS[worker]),
                "note": "Complete the login in the window/browser that opened, then refresh status."}

    @app.post("/api/repo")
    def repo_status(body: dict) -> dict:
        repo = Path(body.get("path", "")).expanduser()
        if not (repo / ".git").exists():
            raise HTTPException(400, f"{repo} is not a git repository")
        s = engine.status(repo)
        s["plan_exists"] = (repo / "docs" / "PLAN.md").exists()
        return s

    @app.post("/api/init")
    def init_repo(body: dict) -> dict:
        from orchestrator.scaffold import scaffold_repo

        repo = Path(body.get("path", "")).expanduser()
        if not repo.is_dir():
            raise HTTPException(400, f"{repo} is not a directory")
        r = scaffold_repo(repo, body.get("project"))
        return {"created": r.created, "skipped": r.skipped}

    @app.post("/api/run")
    def start_run(body: dict) -> dict:
        repo = Path(body.get("path", "")).expanduser()
        if not (repo / ".git").exists():
            raise HTTPException(400, f"{repo} is not a git repository")
        workers = body.get("workers") or ["claude", "codex"]
        prompt = body.get("prompt") or None
        with _run_lock:
            if _run_active.is_set():
                raise HTTPException(409, "a run is already in progress")
            _run_active.set()
        threading.Thread(target=_run_engine, args=(repo, prompt, workers), daemon=True).start()
        return {"started": True}

    @app.get("/api/events")
    def events() -> StreamingResponse:
        def stream():
            yield "retry: 3000\n\n"
            while True:
                item = _events.get()
                yield f"data: {json.dumps(item)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
