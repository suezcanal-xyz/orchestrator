import json
import subprocess

import pytest

from orchestrator.workers.opencode import (
    OpenCodeWorker,
    _iter_json_objects,
    _parse_events,
)


def test_iter_json_objects_handles_array_object_and_ndjson():
    assert list(_iter_json_objects('[{"a":1},{"b":2}]')) == [{"a": 1}, {"b": 2}]
    assert list(_iter_json_objects('{"a":1}')) == [{"a": 1}]
    assert list(_iter_json_objects('{"a":1}\n{"b":2}\n')) == [{"a": 1}, {"b": 2}]
    assert list(_iter_json_objects("")) == []


def test_parse_events_extracts_last_text_and_usage():
    stream = "\n".join(
        json.dumps(o)
        for o in [
            {"type": "step", "text": "thinking"},
            {"type": "message", "content": "final answer here"},
            {"type": "usage", "usage": {"input": 1200, "output": 300, "cost": 0.004}},
        ]
    )
    text, usage = _parse_events(stream)
    assert text == "final answer here"
    assert usage["input_tokens"] == 1200
    assert usage["output_tokens"] == 300
    assert usage["cost_usd"] == pytest.approx(0.004)


class _FakeProc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_invoke_builds_expected_args(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProc(json.dumps({"type": "message", "text": "done"}))

    monkeypatch.setattr(
        "orchestrator.workers.base.shutil.which", lambda n: f"/usr/bin/{n}"
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    w = OpenCodeWorker(model="anthropic/claude-sonnet-4")
    resp = w._invoke(tmp_path, "big prompt " * 500, timeout=60, allow_edit=True)

    args = captured["args"]
    assert args[0] == "/usr/bin/opencode"
    assert args[1] == "run"
    assert "--dir" in args and str(tmp_path) in args
    assert "--format" in args and "json" in args
    assert "--model" in args and "anthropic/claude-sonnet-4" in args
    assert "--auto" in args  # allow_edit=True
    assert "--file" in args
    # the variable-length prompt is NOT in argv
    assert not any("big prompt big prompt" in str(a) for a in args)
    assert resp.ok and resp.summary == "done"


def test_invoke_readonly_omits_auto(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _FakeProc(json.dumps({"type": "message", "text": "read-only reply"}))

    monkeypatch.setattr(
        "orchestrator.workers.base.shutil.which", lambda n: f"/usr/bin/{n}"
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    w = OpenCodeWorker()
    w._invoke(tmp_path, "inspect please", timeout=60, allow_edit=False)
    assert "--auto" not in captured["args"]


def test_invoke_timeout_returns_error(monkeypatch, tmp_path):
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr(
        "orchestrator.workers.base.shutil.which", lambda n: f"/usr/bin/{n}"
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = OpenCodeWorker()._invoke(tmp_path, "x", timeout=1, allow_edit=True)
    assert not resp.ok
    assert "timed out" in resp.error


def test_invoke_maps_nim_api_key_for_opencode(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["env"] = kwargs["env"]
        return _FakeProc(json.dumps({"type": "message", "text": "done"}))

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NIM_API_KEY", "nim-test-key")
    monkeypatch.setattr(
        "orchestrator.workers.base.shutil.which", lambda n: f"/usr/bin/{n}"
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    OpenCodeWorker()._invoke(tmp_path, "inspect please", timeout=60, allow_edit=False)

    assert captured["env"]["NVIDIA_API_KEY"] == "nim-test-key"
