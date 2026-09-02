"""docs/PLAN.md parser and writer (spec section 3).

PLAN.md is the durable, human-readable project memory. It carries a small
YAML frontmatter block for the structured project/version/milestone fields
(spec section 2) and a fixed sequence of `## ` sections. Unknown or
custom sections are preserved on round-trip; the `## Tasks` section is
regenerated from a TaskGraph when one is supplied, since the task list's
source of truth is the structured JSON store (spec section 8), not prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from orchestrator.milestone import ProjectMeta
from orchestrator.task_graph import TaskGraph

CANONICAL_SECTIONS = [
    "Project",
    "Strategic Objective",
    "Current Version",
    "Target Version",
    "Active Milestone",
    "Current State",
    "Requirements",
    "Known Bugs",
    "Tasks",
    "Dependencies",
    "Acceptance Criteria",
    "Verification Commands",
    "Evidence",
    "Decisions",
    "Blockers",
    "Completed Work",
    "Deferred / Not Now",
    "Change History",
]

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


class PlanError(Exception):
    pass


@dataclass
class PlanDocument:
    meta: ProjectMeta
    sections: dict[str, str] = field(default_factory=dict)
    # section names in the order they should render; extras appended after
    order: list[str] = field(default_factory=lambda: list(CANONICAL_SECTIONS))

    def get_section(self, name: str) -> str:
        return self.sections.get(name, "").strip()

    def set_section(self, name: str, body: str) -> None:
        self.sections[name] = body.rstrip() + "\n"
        if name not in self.order:
            self.order.append(name)

    def append_to_section(self, name: str, line: str) -> None:
        current = self.sections.get(name, "").rstrip()
        self.sections[name] = (current + "\n" + line).strip() + "\n" if current else line.strip() + "\n"
        if name not in self.order:
            self.order.append(name)

    def append_change_history(self, text: str, when: date | None = None) -> None:
        when = when or date.today()
        entry = f"### {when.isoformat()}\n\n{text.strip()}\n"
        current = self.sections.get("Change History", "").rstrip()
        self.sections["Change History"] = (current + "\n\n" + entry).strip() + "\n" if current else entry
        if "Change History" not in self.order:
            self.order.append("Change History")

    def sync_task_section(self, graph: TaskGraph) -> None:
        """Regenerate the `## Tasks` section as a table from the canonical TaskGraph."""
        tasks = sorted(graph.all(), key=lambda t: t.id)
        if not tasks:
            self.set_section("Tasks", "_No tasks yet._")
            return
        lines = ["| ID | Title | Status | Priority | Depends on |", "|---|---|---|---|---|"]
        for t in tasks:
            deps = ", ".join(t.depends_on) or "-"
            lines.append(f"| {t.id} | {t.title} | {t.status} | {t.priority} | {deps} |")
        self.set_section("Tasks", "\n".join(lines))

    def render(self) -> str:
        fm = yaml.safe_dump(self.meta.to_dict(), sort_keys=False).strip()
        parts = [f"---\n{fm}\n---\n", "# PROJECT PLAN\n"]
        seen_order = list(dict.fromkeys(self.order))
        for name in seen_order:
            body = self.sections.get(name, "").strip()
            if not body:
                body = "_Not yet defined._"
            parts.append(f"## {name}\n\n{body}\n")
        return "\n".join(parts).rstrip() + "\n"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")


def parse(text: str) -> PlanDocument:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise PlanError("PLAN.md is missing the YAML frontmatter block")
    fm_raw = yaml.safe_load(m.group(1)) or {}
    meta = ProjectMeta.from_dict(fm_raw)
    body = text[m.end():]

    headers = list(_SECTION_RE.finditer(body))
    sections: dict[str, str] = {}
    order: list[str] = []
    for i, hm in enumerate(headers):
        name = hm.group(1).strip()
        start = hm.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        content = body[start:end].strip()
        sections[name] = content
        order.append(name)

    # Preserve canonical ordering first, then any custom sections found in the file.
    full_order = list(CANONICAL_SECTIONS)
    for name in order:
        if name not in full_order:
            full_order.append(name)

    return PlanDocument(meta=meta, sections=sections, order=full_order)


def load(path: Path) -> PlanDocument:
    return parse(path.read_text(encoding="utf-8"))


def new_plan(
    project: str,
    current_version: str = "0.0.0",
    target_version: str = "0.1.0",
    active_milestone: str = "",
    strategic_objective: str = "",
) -> PlanDocument:
    from orchestrator.milestone import MilestoneStatus

    meta = ProjectMeta(
        project=project,
        current_version=current_version,
        target_version=target_version,
        active_milestone=active_milestone,
        status=MilestoneStatus.IN_PROGRESS,
    )
    doc = PlanDocument(meta=meta)
    doc.set_section("Project", project)
    doc.set_section("Strategic Objective", strategic_objective or "_Not yet defined._")
    doc.set_section("Current Version", current_version)
    doc.set_section("Target Version", target_version)
    doc.set_section("Active Milestone", active_milestone or "_Not yet defined._")
    doc.set_section("Tasks", "_No tasks yet._")
    return doc
