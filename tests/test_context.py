import subprocess

from orchestrator import context


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "README.md").write_text("# Demo\n\nA demo project.\n", encoding="utf-8")
    (path / "AGENTS.md").write_text("Do not touch src/legacy/.\n", encoding="utf-8")
    (path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("# TODO: fix this properly\nx = 1\n", encoding="utf-8")
    (path / "src" / "legacy").mkdir()
    (path / "src" / "legacy" / "old.py").write_text("# DEPRECATED module\n", encoding="utf-8")
    (path / "tests").mkdir()
    (path / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (path / "vendor").mkdir()
    (path / "vendor" / "lib.js").write_text("// vendored\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)
    return path


def test_build_context_finds_the_basics(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    ctx = context.build_context(repo)
    assert "Demo" in ctx.readme_excerpt
    assert "legacy" in ctx.agents_md
    assert any("pyproject.toml" in m for m in ctx.manifests)
    assert "tests" in ctx.test_dirs
    assert ctx.recent_commits and "initial" in ctx.recent_commits[0]


def test_markers_detected_with_location(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    ctx = context.build_context(repo)
    kinds = {m.kind for m in ctx.markers}
    assert "TODO" in kinds
    assert "DEPRECATED" in kinds
    todo = next(m for m in ctx.markers if m.kind == "TODO")
    assert todo.path == "src/app.py"
    assert todo.line == 1


def test_classification_hints_flag_vendor_and_legacy(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    ctx = context.build_context(repo)
    assert ctx.classification_hints.get("vendor") == "VENDOR"
    assert ctx.classification_hints.get("src/legacy") == "LEGACY"


def test_focused_context_includes_hinted_file_body(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    ctx = context.build_context(repo)
    block = context.focused_context(ctx, ["src/app.py"])
    assert "src/app.py" in block
    assert "TODO: fix this properly" in block


def test_prompt_block_is_bounded(tmp_path):
    repo = _init_repo(tmp_path / "demo")
    ctx = context.build_context(repo)
    block = ctx.to_prompt_block(max_chars=500)
    assert len(block) <= 500
