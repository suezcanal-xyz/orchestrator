"""Local onboarding dashboard (optional `dashboard` extra).

`create_app()` builds the FastAPI app; `orchestrator onboarding` serves it
on 127.0.0.1. Nothing else in the package imports this module, so the core
has no FastAPI dependency.
"""

from __future__ import annotations


def create_app():  # pragma: no cover - thin re-export
    from orchestrator.dashboard.app import create_app as _create_app

    return _create_app()
