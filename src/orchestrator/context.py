"""Lightweight repository context builder (spec section 9, 10).

Runs before any modification. Produces a concise map of the repository --
never the whole tree -- so a worker gets task-specific context instead of a
blind dump. Classification (CURRENT/LEGACY/UNKNOWN/DEPRECATED/GENERATED/
VENDOR) here is advisory only: it flags candidates for a worker or human to
investigate, never proof of dead code. Deleting anything on the strength of
this module alone is out of scope by design (spec section 9).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

IGNORE_DIRS = {
    ".git", ".orchestrator", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".turbo", "target", ".pytest_cache", ".mypy_cache",
    "vendor", ".idea", ".vscode", "coverage", ".ruff_cache",
}

MANIFEST_NAMES = {
    "package.json", "pyproject.toml", "setup.py", "requirements.txt",
    "requirements-dev.txt", "Cargo.toml", "go.mod", "composer.json", "Gemfile",
}
LOCKFILE_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "composer.lock",
}
ENV_EXAMPLE_PATTERNS = ("*.env.example", ".env.example", ".env.sample", "*.env.sample")
CI_GLOBS = (".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml", ".circleci/config.yml")
DB_SCHEMA_HINTS = ("schema.sql", "schema.prisma")
API_SCHEMA_HINTS = ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.json")
TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec", "specs"}
MIGRATION_DIR_NAMES = {"migrations", "alembic", "migrate"}

MARKER_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK|DEPRECATED|LEGACY)\b[:\s]?(.{0,120})")
TEXT_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".php",
    ".md", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sql", ".sh", ".ps1",
}
MAX_MARKER_SCAN_FILES = 4000
MAX_MARKER_HITS = 200
MAX_FILE_SIZE_FOR_SCAN = 512_000

LegacyClass = str  # one of: CURRENT, LEGACY, UNKNOWN, DEPRECATED, GENERATED, VENDOR

_CLASS_PATTERNS: list[tuple[re.Pattern, LegacyClass]] = [
    (re.compile(r"(^|/)(vendor|node_modules|third_party)(/|$)"), "VENDOR"),
    (re.compile(r"(^|/)(dist|build|out|generated|\.next)(/|$)"), "GENERATED"),
    (re.compile(r"\.min\.(js|css)$"), "GENERATED"),
    (re.compile(r"(^|/)(legacy|_archive|deprecated|old)(/|$)", re.IGNORECASE), "LEGACY"),
    (re.compile(r"(^|/)(migrations|alembic)(/|$)"), "CURRENT"),
]


@dataclass
class Marker:
    path: str
    line: int
    kind: str
    text: str


@dataclass
class RepoContext:
    root: Path
    readme_excerpt: str = ""
    agents_md: str = ""
    claude_md: str = ""
    manifests: list[str] = field(default_factory=list)
    lockfiles: list[str] = field(default_factory=list)
    env_examples: list[str] = field(default_factory=list)
    ci_configs: list[str] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)
    db_schema_paths: list[str] = field(default_factory=list)
    migration_dirs: list[str] = field(default_factory=list)
    api_schema_paths: list[str] = field(default_factory=list)
    docs_paths: list[str] = field(default_factory=list)
    recent_commits: list[str] = field(default_factory=list)
    directory_tree: list[str] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    classification_hints: dict[str, LegacyClass] = field(default_factory=dict)

    def to_prompt_block(self, max_chars: int = 4000) -> str:
        lines = [f"# Repository context: {self.root.name}", ""]
        if self.readme_excerpt:
            lines += ["## README (excerpt)", self.readme_excerpt.strip()[:800], ""]
        if self.agents_md:
            lines += ["## AGENTS.md", self.agents_md.strip()[:1200], ""]
        if self.claude_md:
            lines += ["## CLAUDE.md", self.claude_md.strip()[:1200], ""]
        lines += ["## Manifests", *self.manifests, ""]
        if self.ci_configs:
            lines += ["## CI", *self.ci_configs, ""]
        if self.test_dirs:
            lines += ["## Test directories", *self.test_dirs, ""]
        if self.migration_dirs or self.db_schema_paths:
            lines += ["## Database", *self.migration_dirs, *self.db_schema_paths, ""]
        if self.api_schema_paths:
            lines += ["## API schemas", *self.api_schema_paths, ""]
        if self.recent_commits:
            lines += ["## Recent history", *self.recent_commits[:15], ""]
        if self.directory_tree:
            lines += ["## Directory tree (pruned)", *self.directory_tree[:120], ""]
        if self.markers:
            lines += ["## TODO/FIXME/legacy markers (sample)"]
            for m in self.markers[:40]:
                lines.append(f"{m.path}:{m.line}: {m.kind} {m.text}".strip())
            lines.append("")
        text = "\n".join(lines)
        return text[:max_chars]


def _read_first(root: Path, names: list[str], max_chars: int = 4000) -> str:
    for name in names:
        p = root / name
        if p.exists() and p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace")[:max_chars]
            except OSError:
                return ""
    return ""


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p)


def _walk(root: Path):
    for dirpath, dirnames, filenames in _os_walk_pruned(root):
        yield dirpath, dirnames, filenames


def _os_walk_pruned(root: Path):
    import os

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        yield Path(dirpath), dirnames, filenames


def classify_path(rel_path: str) -> LegacyClass:
    for pattern, cls in _CLASS_PATTERNS:
        if pattern.search(rel_path):
            return cls
    return "UNKNOWN"


def build_context(root: Path) -> RepoContext:
    root = root.resolve()
    ctx = RepoContext(root=root)

    ctx.readme_excerpt = _read_first(root, ["README.md", "readme.md", "README.rst", "README"])
    ctx.agents_md = _read_first(root, ["AGENTS.md"])
    ctx.claude_md = _read_first(root, ["CLAUDE.md"])

    for dirpath, dirnames, filenames in _walk(root):
        rel_dir = _rel(root, dirpath)
        for name in filenames:
            if name in MANIFEST_NAMES:
                ctx.manifests.append(_rel(root, dirpath / name))
            if name in LOCKFILE_NAMES:
                ctx.lockfiles.append(_rel(root, dirpath / name))
            if name in {"openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.json"}:
                ctx.api_schema_paths.append(_rel(root, dirpath / name))
            if name in DB_SCHEMA_HINTS:
                ctx.db_schema_paths.append(_rel(root, dirpath / name))
            if ".env.example" in name or ".env.sample" in name:
                ctx.env_examples.append(_rel(root, dirpath / name))
            if rel_dir == ".github/workflows" or dirpath.name == "workflows":
                if name.endswith((".yml", ".yaml")):
                    ctx.ci_configs.append(_rel(root, dirpath / name))
            if name in {".gitlab-ci.yml"}:
                ctx.ci_configs.append(_rel(root, dirpath / name))
        base = dirpath.name.lower()
        if base in TEST_DIR_NAMES and rel_dir not in ctx.test_dirs:
            ctx.test_dirs.append(rel_dir)
        if base in MIGRATION_DIR_NAMES and rel_dir not in ctx.migration_dirs:
            ctx.migration_dirs.append(rel_dir)
        if base == "docs" and rel_dir not in ctx.docs_paths:
            ctx.docs_paths.append(rel_dir)

    ctx.recent_commits = _recent_git_log(root)
    ctx.directory_tree = _directory_tree(root)
    ctx.markers, ctx.classification_hints = _scan_markers(root)

    return ctx


def _recent_git_log(root: Path, n: int = 20) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "log", f"-n{n}", "--pretty=%h %ad %s", "--date=short"],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0:
            return [line for line in proc.stdout.splitlines() if line.strip()]
    except FileNotFoundError:
        pass
    return []


def _directory_tree(root: Path, max_depth: int = 2, max_entries: int = 150) -> list[str]:
    out: list[str] = []
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in _walk(root):
        depth = len(dirpath.parts) - root_depth
        if depth > max_depth:
            dirnames[:] = []
            continue
        rel = _rel(root, dirpath)
        if rel != ".":
            out.append(rel + "/")
        if len(out) >= max_entries:
            break
    return out


def _scan_markers(root: Path) -> tuple[list[Marker], dict[str, LegacyClass]]:
    import os

    markers: list[Marker] = []
    hints: dict[str, LegacyClass] = {}
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath)
        rel_dir = _rel(root, dirpath)
        cls = classify_path(rel_dir)
        if cls != "UNKNOWN":
            hints[rel_dir] = cls
        # Classify children we are about to prune -- a vendor/ or node_modules/
        # directory is worth flagging even though we never descend into its
        # (possibly huge, possibly vendored) contents.
        for d in dirnames:
            if d in IGNORE_DIRS:
                child_rel = _rel(root, dirpath / d)
                child_cls = classify_path(child_rel)
                if child_cls != "UNKNOWN":
                    hints[child_rel] = child_cls
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if scanned >= MAX_MARKER_SCAN_FILES or len(markers) >= MAX_MARKER_HITS:
                return markers, hints
            p = dirpath / name
            if p.suffix not in TEXT_EXTENSIONS:
                continue
            try:
                if p.stat().st_size > MAX_FILE_SIZE_FOR_SCAN:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1
            rel_path = _rel(root, p)
            for i, line in enumerate(text.splitlines(), start=1):
                m = MARKER_RE.search(line)
                if m:
                    markers.append(Marker(path=rel_path, line=i, kind=m.group(1), text=m.group(2).strip()))
                    if len(markers) >= MAX_MARKER_HITS:
                        break
    return markers, hints


def focused_context(ctx: RepoContext, files_hint: list[str], max_chars_per_file: int = 2000) -> str:
    """Task-specific slice: the general map plus excerpts of hinted files/dirs only.

    This is what should actually be handed to a worker for a given task --
    never the raw context.to_prompt_block() alone and never the whole repo.
    """
    lines = [ctx.to_prompt_block(max_chars=2500), "", "## Task-specific files", ""]
    for hint in files_hint:
        p = ctx.root / hint
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = "<unreadable>"
            lines.append(f"### {hint}\n```\n{text[:max_chars_per_file]}\n```\n")
        elif p.is_dir():
            entries = sorted(x.name for x in p.iterdir())[:50]
            lines.append(f"### {hint}/ (listing)\n" + "\n".join(f"- {e}" for e in entries) + "\n")
        else:
            lines.append(f"### {hint} (does not exist yet)\n")
    return "\n".join(lines)
