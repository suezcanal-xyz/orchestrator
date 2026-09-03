import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from conftest import init_repo  # noqa: E402
from orchestrator import extensions  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    # never actually spawn a login process during tests
    import orchestrator.dashboard.app as appmod

    spawned = []
    monkeypatch.setattr(appmod, "_spawn_login", lambda w: spawned.append(w))
    app = appmod.create_app()
    c = TestClient(app)
    c._spawned = spawned  # type: ignore[attr-defined]
    return c


def test_doctor_endpoint_shape(client):
    data = client.get("/api/doctor").json()
    assert isinstance(data, list)
    names = {d["name"] for d in data}
    assert {"codex", "claude", "opencode"} <= names
    for d in data:
        assert set(d) == {"name", "found", "path", "worker_registered", "auth_note"}


def test_login_endpoint_is_nonblocking_and_validates(client):
    r = client.post("/api/login/claude")
    assert r.status_code == 200
    assert client._spawned == ["claude"]
    assert client.post("/api/login/bogus").status_code == 400


def test_repo_and_init_roundtrip(client, tmp_path):
    repo = init_repo(tmp_path / "demo")
    r = client.post("/api/repo", json={"path": str(repo)})
    assert r.status_code == 200
    assert r.json()["plan_exists"] is False

    r = client.post("/api/init", json={"path": str(repo), "project": "demo"})
    assert r.status_code == 200
    assert "docs/PLAN.md" in r.json()["created"]

    # idempotent
    r = client.post("/api/init", json={"path": str(repo)})
    assert "docs/PLAN.md" in r.json()["skipped"]

    r = client.post("/api/repo", json={"path": str(repo)})
    assert r.json()["plan_exists"] is True


def test_repo_rejects_non_git(client, tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert client.post("/api/repo", json={"path": str(d)}).status_code == 400


def test_events_stream_emits_hook_payloads(client):
    import orchestrator.dashboard.app as appmod

    # drain anything already queued
    while not appmod._events.empty():
        appmod._events.get_nowait()

    extensions.run_hooks("task_done", task=type("T", (), {"id": "X-1"})(), outcome=None)
    item = appmod._events.get(timeout=2)
    assert item["event"] == "task_done"
    assert "X-1" in json.dumps(item)
