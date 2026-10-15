"""Opt-in local Ollama coding agent via OpenCode.

This adapter does not constitute an OS sandbox or network egress control.
"""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from orchestrator.workers.base import WorkerResponse
from orchestrator.workers.opencode import OpenCodeWorker

_LOCAL_URL = "http://127.0.0.1:11434"
_DEFAULT_MODEL = "qwen3:4b"
_MODEL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")


def validate_model(model: str) -> str:
    """Reject provider prefixes, remote/cloud tags and unsafe CLI values."""
    if not _MODEL_RE.fullmatch(model):
        raise ValueError("ORCHESTRATOR_OLLAMA_MODEL must be a bare Ollama model ID")
    if "cloud" in model.casefold():
        raise ValueError("Cloud model IDs are not allowed with ollama-local")
    return model


def opencode_local_config(model: str, *, allow_edit: bool) -> str:
    """Fixed loopback-only model provider with explicit tool permissions."""
    validate_model(model)
    permissions = {
        "*": "deny",
        "read": "allow",
        "glob": "allow",
        "grep": "allow",
        "lsp": "allow",
        "external_directory": "deny",
        "edit": "allow" if allow_edit else "deny",
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "task": "deny",
    }
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"ollama/{model}",
        "enabled_providers": ["ollama"],
        "autoupdate": False,
        "share": "disabled",
        "provider": {
            "ollama": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Local Ollama",
                "options": {"baseURL": f"{_LOCAL_URL}/v1"},
                "models": {model: {"name": model}},
            }
        },
        "permission": permissions,
        "agent": {
            "plan": {"permission": permissions},
            "build": {"permission": permissions},
        },
    }
    return json.dumps(config, separators=(",", ":"))


def check_installed_model(model: str) -> str | None:
    """Check only localhost and fail closed if the selected model is absent."""
    try:
        request = Request(
            f"{_LOCAL_URL}/api/tags", headers={"Accept": "application/json"}
        )
        with urlopen(request, timeout=3) as response:
            payload = json.load(response)
        names = [
            m.get("name") for m in payload.get("models", []) if isinstance(m, dict)
        ]
        if model not in names:
            return f"Model {model!r} not installed. Run: ollama pull {model}"
    except (
        URLError,
        HTTPError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        return f"Cannot query Ollama at {_LOCAL_URL}: {type(exc).__name__}. Start Ollama first."
    return None


class OllamaLocalWorker(OpenCodeWorker):
    """Selected explicitly by --worker ollama-local, never by default."""

    name = "ollama-local"

    def __init__(self, executable: str = "opencode", model: str | None = None) -> None:
        chosen = (
            model
            if model is not None
            else os.environ.get("ORCHESTRATOR_OLLAMA_MODEL", _DEFAULT_MODEL)
        )
        self.local_model = validate_model(chosen.strip())
        self.edit_opt_in = os.environ.get("ORCHESTRATOR_OLLAMA_ALLOW_EDIT") == "1"
        super().__init__(
            executable=executable,
            model=f"ollama/{self.local_model}",
            agent="by-mode",
            auto_approve_edit=False,
        )

    def _invoke(
        self, cwd, prompt, *, timeout, allow_edit, structured=False
    ) -> WorkerResponse:
        if allow_edit and not self.edit_opt_in:
            return WorkerResponse(
                ok=False,
                summary="",
                raw_output="",
                duration_seconds=0,
                worker=self.name,
                error="Local edits disabled. Set ORCHESTRATOR_OLLAMA_ALLOW_EDIT=1 only in an isolated lab.",
            )
        error = check_installed_model(self.local_model)
        if error:
            return WorkerResponse(
                ok=False,
                summary="",
                raw_output="",
                duration_seconds=0,
                worker=self.name,
                error=error,
            )
        self.config_content = opencode_local_config(
            self.local_model, allow_edit=allow_edit
        )
        result = super()._invoke(
            cwd, prompt, timeout=timeout, allow_edit=allow_edit, structured=structured
        )
        result.worker = self.name
        result.extra = {
            **result.extra,
            "provider": "ollama-local",
            "model": self.local_model,
        }
        return result
