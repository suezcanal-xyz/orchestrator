"""Offline unit tests: neither Ollama nor OpenCode is required."""

import json
import subprocess

import pytest

from orchestrator.cli import _resolve_workers
from orchestrator.workers.ollama import (
    OllamaLocalWorker,
    opencode_local_config,
    validate_model,
)


def test_resolver_preserves_existing_workers():
    assert _resolve_workers(("ollama-local",))[0].name == "ollama-local"
    assert _resolve_workers(("opencode",))[0].name == "opencode"


@pytest.mark.parametrize(
    "bad",
    [
        "ollama/qwen3:4b",
        "gpt-oss:20b-cloud",
        "glm-5:cloud",
        "../secret",
        "bad model",
        "",
        "--model",
        "/etc/passwd",
    ],
)
def test_invalid_model_rejected(bad):
    with pytest.raises(ValueError):
        validate_model(bad)


def test_readonly_config_is_local_only():
    config = json.loads(opencode_local_config("qwen3:4b", allow_edit=False))
    assert config["enabled_providers"] == ["ollama"]
    assert config["model"] == "ollama/qwen3:4b"
    assert (
        config["provider"]["ollama"]["options"]["baseURL"]
        == "http://127.0.0.1:11434/v1"
    )
    assert config["permission"]["bash"] == "deny"
    assert config["permission"]["edit"] == "deny"
    assert config["permission"]["external_directory"] == "deny"
    assert config["agent"]["plan"]["permission"]["edit"] == "deny"
    assert config["share"] == "disabled"


def test_edit_disabled_without_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("ORCHESTRATOR_OLLAMA_ALLOW_EDIT", raising=False)
    worker = OllamaLocalWorker()
    result = worker._invoke(tmp_path, "test", timeout=2, allow_edit=True)
    assert not result.ok
    assert "disabled" in result.error


def test_model_preflight_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "orchestrator.workers.ollama.check_installed_model",
        lambda model: "not installed",
    )
    result = OllamaLocalWorker()._invoke(tmp_path, "test", timeout=2, allow_edit=False)
    assert not result.ok
    assert result.error == "not installed"


def test_readonly_and_edit_paths_are_pinned(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCHESTRATOR_OLLAMA_ALLOW_EDIT", "1")
    monkeypatch.setattr(
        "orchestrator.workers.ollama.check_installed_model", lambda model: None
    )
    monkeypatch.setattr(
        "orchestrator.workers.base.shutil.which", lambda n: f"/usr/bin/{n}"
    )
    called = []

    class FakeProc:
        returncode = 0
        stdout = '{"type":"message","text":"ok"}'
        stderr = ""

    def fake_run(args, **kwargs):
        called.append((args, kwargs))
        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    worker = OllamaLocalWorker(model="qwen3:4b")
    for edit in (False, True):
        result = worker._invoke(tmp_path, "test", timeout=3, allow_edit=edit)
        assert result.ok and result.worker == "ollama-local"
        assert result.extra["model"] == "qwen3:4b"
    for edit, (args, kwargs) in zip((False, True), called):
        config = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
        assert args[args.index("--model") + 1] == "ollama/qwen3:4b"
        assert args[args.index("--agent") + 1] == ("build" if edit else "plan")
        assert "--auto" not in args
        assert config["enabled_providers"] == ["ollama"]
        assert config["permission"]["edit"] == ("allow" if edit else "deny")


def test_preflight_checks_localhost_with_exact_name(monkeypatch):
    from orchestrator.workers import ollama

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"models":[{"name":"qwen3:4b"}]}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)
    assert ollama.check_installed_model("qwen3:4b") is None
    assert "127.0.0.1" in captured["url"]
    assert "ollama pull" in ollama.check_installed_model("qwen3:8b")
