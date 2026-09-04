"""`orchestrator init`: drop a starter docs/PLAN.md + AGENTS.md into a repo.

Both the CLI command and the dashboard's `/api/init` route call
`scaffold_repo`. It never overwrites an existing file -- a half-filled
PLAN.md is the durable project memory (spec section 1) and must not be
clobbered.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from orchestrator import plan as plan_mod


@dataclass
class ScaffoldResult:
    created: list[str]
    skipped: list[str]


def _agents_template() -> str:
    return (resources.files("orchestrator.templates") / "AGENTS.md").read_text(
        encoding="utf-8"
    )


def scaffold_repo(repo: Path, project: str | None = None) -> ScaffoldResult:
    repo = Path(repo)
    project = project or repo.name
    created: list[str] = []
    skipped: list[str] = []

    plan_path = repo / "docs" / "PLAN.md"
    if plan_path.exists():
        skipped.append("docs/PLAN.md")
    else:
        plan_mod.new_plan(project).save(plan_path)
        created.append("docs/PLAN.md")

    agents_path = repo / "AGENTS.md"
    if agents_path.exists():
        skipped.append("AGENTS.md")
    else:
        agents_path.write_text(_agents_template(), encoding="utf-8")
        created.append("AGENTS.md")

    return ScaffoldResult(created=created, skipped=skipped)
