"""Engine-level test of the closed development loop, with scripted (non-CLI)
workers standing in for real Codex/Claude calls -- see spec section 22 for
the full 17-step acceptance scenario this mirrors at the engine level. The
live version against real `codex exec` / `claude -p` is a separate,
explicitly-invoked test (test_integration_v0_1_0_live.py)."""

import re
import subprocess

import pytest
from conftest import init_repo

from orchestrator import engine, git, state
from orchestrator.task_graph import Task, TaskGraph
from orchestrator.workers.base import Worker, WorkerResponse

TEST_ADD_PY = "from add_mod import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
TEST_MUL_PY = "from mul_mod import mul\n\ndef test_mul():\n    assert mul(2, 3) == 6\n"


class ScriptedWorker(Worker):
    """Stands in for a real CLI worker: parses which task/stage it was asked
    to handle out of the prompt text (the same prompts base.py builds for a
    real worker) and runs a scripted file edit instead of shelling out."""

    def __init__(self, name, actions):
        self.name = name
        self._actions = actions
        self.calls: list[tuple[str, str]] = []
        self.prompts: list[str] = []

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        m = re.search(r"# (Review task|Debug task|Task) ([A-Z]+-\d+)", prompt)
        stage = (
            "review"
            if m and m.group(1) == "Review task"
            else "debug"
            if m and m.group(1) == "Debug task"
            else "implement"
        )
        task_id = m.group(2) if m else "?"
        self.calls.append((task_id, stage))
        self.prompts.append(prompt)
        action = self._actions.get((task_id, stage))
        if action:
            action(cwd)
        return WorkerResponse(
            ok=True,
            summary="APPROVE" if stage == "review" else f"{stage} done for {task_id}",
            raw_output="APPROVE" if stage == "review" else "",
            duration_seconds=0.01,
            worker=self.name,
        )


class SequencedReviewWorker(ScriptedWorker):
    def __init__(self, name, verdicts):
        super().__init__(name, {})
        self._verdicts = iter(verdicts)

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        if "# Review task" not in prompt:
            return super()._invoke(
                cwd,
                prompt,
                timeout=timeout,
                allow_edit=allow_edit,
                structured=structured,
            )
        task_id = re.search(r"# Review task ([A-Z]+-\d+)", prompt).group(1)
        verdict = next(self._verdicts)
        self.calls.append((task_id, "review"))
        self.prompts.append(prompt)
        return WorkerResponse(
            ok=True,
            summary=verdict,
            raw_output=verdict,
            duration_seconds=0.01,
            worker=self.name,
        )


def write_correct_add(cwd):
    (cwd / "add_mod.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )


def write_wrong_mul(cwd):
    # intentional bug: addition instead of multiplication (spec section 22 step 11)
    (cwd / "mul_mod.py").write_text(
        "def mul(a, b):\n    return a + b\n", encoding="utf-8"
    )


def write_correct_mul(cwd):
    (cwd / "mul_mod.py").write_text(
        "def mul(a, b):\n    return a * b\n", encoding="utf-8"
    )


@pytest.fixture
def demo_repo(tmp_path):
    return init_repo(
        tmp_path / "demo",
        files={"tests/test_add.py": TEST_ADD_PY, "tests/test_mul.py": TEST_MUL_PY},
    )


def _seed_tasks(repo):
    graph = TaskGraph(
        [
            Task(
                id="TEST-001",
                title="Implement add()",
                status="READY",
                acceptance=["add(2, 3) == 5"],
                verification=["python -m pytest tests/test_add.py -q"],
                files_hint=["add_mod.py"],
            ),
            Task(
                id="TEST-002",
                title="Implement mul()",
                status="READY",
                acceptance=["mul(2, 3) == 6"],
                verification=["python -m pytest tests/test_mul.py -q"],
                files_hint=["mul_mod.py"],
            ),
        ]
    )
    state.save_task_store(repo, graph)
    return graph


def test_closed_loop_happy_path_and_cross_model_debug(demo_repo):
    repo = demo_repo
    _seed_tasks(repo)
    main_head_before = git.head_commit(repo)

    claude = ScriptedWorker(
        "claude",
        {
            ("TEST-001", "implement"): write_correct_add,
            (
                "TEST-002",
                "debug",
            ): write_correct_mul,  # cross-model: claude fixes codex's bug
        },
    )
    codex = ScriptedWorker(
        "codex",
        {
            ("TEST-002", "implement"): write_wrong_mul,
        },
    )

    result = engine.run(repo=repo, prompt_text=None, implement_workers=[claude, codex])

    outcomes = {o.task_id: o for o in result.task_outcomes}
    assert outcomes["TEST-001"].status == "DONE"
    assert outcomes["TEST-001"].debug_attempts == 0

    assert outcomes["TEST-002"].status == "DONE"
    assert (
        outcomes["TEST-002"].debug_attempts == 1
    )  # failed once, fixed on first debug attempt

    # cross-model debugging actually happened: codex implemented, claude debugged
    assert ("TEST-002", "implement") in codex.calls
    assert ("TEST-002", "debug") in claude.calls

    # protected branch untouched: no new commit landed on main (spec section
    # 17, 22 step 17). docs/PLAN.md and .gitignore are legitimately modified
    # in the main working tree -- that's the durable-memory design (spec
    # section 1) -- but nothing was committed onto the branch, and no task
    # code leaked out of its worktree.
    assert git.current_branch(repo) == "main"
    assert git.head_commit(repo) == main_head_before
    assert not (repo / "add_mod.py").exists()  # only the worktree has it, not main
    assert not (repo / "mul_mod.py").exists()
    assert ".orchestrator/" in (repo / ".gitignore").read_text(encoding="utf-8")

    # PLAN.md updated with actual state
    assert result.plan.get_section("Tasks")
    assert "TEST-001" in result.plan.get_section("Tasks")
    assert "DONE" in result.plan.get_section("Tasks")

    # VERDICT.md produced
    assert result.run_paths.verdict.exists()
    assert result.verdict is not None

    # evidence trail exists for both tasks
    assert (result.run_paths.diffs_dir / "TEST-001.diff").exists()
    assert (result.run_paths.diffs_dir / "TEST-002.diff").exists()
    assert (result.run_paths.evidence_dir / "TEST-002.debug-1.json").exists()

    # per-task focused context: TEST-001's implement prompt names its own
    # hinted file, not the other task's
    impl_prompt = next(
        p for p, (tid, st) in zip(claude.prompts, claude.calls) if tid == "TEST-001"
    )
    assert "add_mod.py" in impl_prompt

    # cost accounting: VERDICT has a Cost section and RunResult carries the summary
    assert "## Cost" in result.run_paths.verdict.read_text(encoding="utf-8")
    assert "totals" in result.usage
    assert (result.run_paths.root / "usage.json").exists()


def test_milestone_gate_blocks_ready_even_when_every_task_is_done(tmp_path):
    """`## Verification Commands` run as an explicit gate in the
    integration worktree: a failing gate command blocks READY_FOR_REVIEW
    even though all tasks are DONE, and is named under ## Milestone Gate."""
    from orchestrator import plan as plan_mod

    doc = plan_mod.new_plan("g", current_version="0.0.0", target_version="0.1.0")
    doc.set_section(
        "Verification Commands",
        '- python -c "pass"\n- python -c "import sys; sys.exit(2)"',
    )
    graph = TaskGraph([Task(id="G-1", title="t", status="DONE")])

    v = engine.build_verdict(tmp_path, doc, graph)
    assert [g.command for g in v.gate] == [
        'python -c "pass"',
        'python -c "import sys; sys.exit(2)"',
    ]
    assert [g.passed for g in v.gate] == [True, False]
    assert v.ready is False  # task DONE but gate failed
    assert v.result_status.value == "BLOCKED"
    r = v.render()
    assert "## Milestone Gate" in r
    assert 'FAIL  python -c "import sys; sys.exit(2)"' in r


def test_milestone_gate_all_pass_with_done_tasks_is_ready(tmp_path):
    from orchestrator import plan as plan_mod

    doc = plan_mod.new_plan("g2", current_version="0.0.0", target_version="0.1.0")
    doc.set_section("Verification Commands", '- python -c "pass"')
    graph = TaskGraph([Task(id="G-1", title="t", status="DONE")])
    v = engine.build_verdict(tmp_path, doc, graph)
    assert v.ready is True
    assert v.gate and all(g.passed for g in v.gate)


def test_verdict_flags_a_milestone_with_no_acceptance_criteria(tmp_path):
    from orchestrator import plan as plan_mod

    doc = plan_mod.new_plan(
        "m", current_version="0.0.0", target_version="0.1.0"
    )  # criteria undefined
    graph = TaskGraph([Task(id="M-1", title="t", status="DONE")])
    v = engine.build_verdict(tmp_path, doc, graph)
    assert v.ready is True  # task is DONE
    assert "task DONE/BLOCKED status only" in v.notes
    assert "Acceptance Criteria" in v.notes


def test_ingest_records_a_blocker_when_criteria_are_undefined(tmp_path, monkeypatch):
    from orchestrator import plan as plan_mod

    repo = init_repo(tmp_path / "ic")
    plan_mod.new_plan("ic").save(repo / "docs" / "PLAN.md")

    def W():
        return ReconcileOnlyWorker()

    r1 = engine.ingest(repo, "do a thing", W())
    blockers = r1.plan.get_section("Blockers")
    assert "Milestone acceptance not defined" in blockers

    r2 = engine.ingest(repo, "another thing", W())  # not duplicated
    assert (
        r2.plan.get_section("Blockers").count("Milestone acceptance not defined") == 1
    )

    # once criteria + commands are filled in, the blocker is cleared
    doc = plan_mod.load(repo / "docs" / "PLAN.md")
    doc.set_section("Acceptance Criteria", "- op returns 1")
    doc.set_section("Verification Commands", '- python -c "pass"')
    doc.save(repo / "docs" / "PLAN.md")
    r3 = engine.ingest(repo, "third", W())
    assert "Milestone acceptance not defined" not in r3.plan.get_section("Blockers")


def test_verdict_checks_integrated_task_work_not_the_untouched_base(tmp_path):
    """Milestone acceptance must be judged against the combined result of
    the run's DONE task branches, not the protected branch (which is never
    merged into in v0). Regression: a run whose tasks all pass their own
    verification was reported NOT READY because the acceptance commands
    were re-run against the untouched base."""
    repo = init_repo(
        tmp_path / "acc",
        files={
            "op.py": "def op():\n    return 0\n",
            "tests/test_op.py": "from op import op\n\ndef test_op():\n    assert op() == 42\n",
            "docs/PLAN.md": (
                "---\nproject: acc\ncurrent_version: 0.0.0\ntarget_version: 0.1.0\n"
                "active_milestone: m\nstatus: IN_PROGRESS\n---\n"
                "# PROJECT PLAN\n\n## Acceptance Criteria\n\n- op() returns 42\n\n"
                "## Verification Commands\n\n- python -m pytest tests/test_op.py -q\n"
            ),
        },
    )
    state.save_task_store(
        repo,
        TaskGraph(
            [
                Task(
                    id="OP-1",
                    title="make op() return 42",
                    status="READY",
                    acceptance=["op() == 42"],
                    verification=["python -m pytest tests/test_op.py -q"],
                    files_hint=["op.py"],
                )
            ]
        ),
    )

    def fix_op(cwd):
        (cwd / "op.py").write_text("def op():\n    return 42\n", encoding="utf-8")

    worker = ScriptedWorker("claude", {("OP-1", "implement"): fix_op})
    result = engine.run(repo=repo, prompt_text=None, implement_workers=[worker])

    assert result.task_outcomes[0].status == "DONE"
    assert result.verdict.ready is True
    assert result.verdict.result_status.value == "READY_FOR_REVIEW"
    # base branch itself was never modified
    assert (repo / "op.py").read_text(encoding="utf-8") == "def op():\n    return 0\n"


def test_run_only_task_ids_executes_just_the_selected_task(tmp_path):
    repo = init_repo(
        tmp_path / "sel",
        files={
            "a.py": "x = 0\n",
            "b.py": "x = 0\n",
            "tests/test_a.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
            "from a import x\n\ndef test_a():\n    assert x == 1\n",
            "tests/test_b.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
            "from b import x\n\ndef test_b():\n    assert x == 1\n",
        },
    )
    state.save_task_store(
        repo,
        TaskGraph(
            [
                Task(
                    id="SEL-1",
                    title="fix a",
                    status="READY",
                    acceptance=["x==1"],
                    verification=["python -m pytest tests/test_a.py -q"],
                    files_hint=["a.py"],
                ),
                Task(
                    id="SEL-2",
                    title="fix b",
                    status="READY",
                    acceptance=["x==1"],
                    verification=["python -m pytest tests/test_b.py -q"],
                    files_hint=["b.py"],
                ),
            ]
        ),
    )
    w = ScriptedWorker(
        "claude",
        {
            ("SEL-1", "implement"): lambda cwd: (cwd / "a.py").write_text(
                "x = 1\n", encoding="utf-8"
            ),
            ("SEL-2", "implement"): lambda cwd: (cwd / "b.py").write_text(
                "x = 1\n", encoding="utf-8"
            ),
        },
    )
    result = engine.run(
        repo=repo, prompt_text=None, implement_workers=[w], only_task_ids={"SEL-1"}
    )
    assert [o.task_id for o in result.task_outcomes] == ["SEL-1"]
    assert result.task_outcomes[0].status == "DONE"
    assert ("SEL-2", "implement") not in w.calls


def test_scoped_run_reports_its_own_status_not_the_milestone_verdict(tmp_path):
    """A --task run that finishes its selected task is SCOPED_OK / ok=True,
    even though the milestone still has an un-run task the verdict marks
    FAIL. The milestone status in PLAN.md is not touched by a scoped run."""
    repo = init_repo(
        tmp_path / "scoped",
        files={
            "a.py": "x = 0\n",
            "b.py": "x = 0\n",
            "tests/test_a.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
            "from a import x\n\ndef test_a():\n    assert x == 1\n",
            "tests/test_b.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
            "from b import x\n\ndef test_b():\n    assert x == 1\n",
            "docs/PLAN.md": (
                "---\nproject: scoped\ncurrent_version: 0.0.0\ntarget_version: 0.1.0\n"
                "active_milestone: m\nstatus: IN_PROGRESS\n---\n# PROJECT PLAN\n\n## Tasks\n\n_x_\n"
            ),
        },
    )
    state.save_task_store(
        repo,
        TaskGraph(
            [
                Task(
                    id="SC-1",
                    title="fix a",
                    status="READY",
                    acceptance=["x==1"],
                    verification=["python -m pytest tests/test_a.py -q"],
                    files_hint=["a.py"],
                ),
                Task(
                    id="SC-2",
                    title="fix b",
                    status="READY",
                    acceptance=["x==1"],
                    verification=["python -m pytest tests/test_b.py -q"],
                    files_hint=["b.py"],
                ),
            ]
        ),
    )
    w = ScriptedWorker(
        "claude",
        {
            ("SC-1", "implement"): lambda cwd: (cwd / "a.py").write_text(
                "x = 1\n", encoding="utf-8"
            ),
        },
    )
    result = engine.run(
        repo=repo, prompt_text=None, implement_workers=[w], only_task_ids={"SC-1"}
    )

    assert result.scoped is True
    assert result.run_status == "SCOPED_OK"
    assert result.ok is True
    assert result.manifest.status == "SCOPED_OK"
    # milestone verdict still sees T-B unfinished
    assert result.verdict.ready is False
    assert "scoped run" in result.verdict.notes
    # PLAN.md milestone status untouched by a scoped run
    from orchestrator import plan as plan_mod

    assert plan_mod.load(repo / "docs" / "PLAN.md").meta.status.value == "IN_PROGRESS"


def test_run_only_task_ids_rejects_an_unknown_or_dependency_gap(tmp_path):
    repo = init_repo(
        tmp_path / "sel2",
        files={
            "tests/test_x.py": "def test_x():\n    assert True\n",
        },
    )
    state.save_task_store(
        repo,
        TaskGraph(
            [
                Task(
                    id="P-1",
                    title="p1",
                    status="READY",
                    verification=["python -m pytest tests/test_x.py -q"],
                ),
                Task(
                    id="P-2",
                    title="p2",
                    status="READY",
                    depends_on=["P-1"],
                    verification=["python -m pytest tests/test_x.py -q"],
                ),
            ]
        ),
    )
    w = ScriptedWorker("claude", {})
    with pytest.raises(ValueError, match="not runnable"):
        engine.run(
            repo=repo, prompt_text=None, implement_workers=[w], only_task_ids={"NOPE"}
        )
    with pytest.raises(
        ValueError, match="not runnable"
    ):  # P-2's dependency P-1 is still pending
        engine.run(
            repo=repo, prompt_text=None, implement_workers=[w], only_task_ids={"P-2"}
        )


def test_run_base_ref_bases_worktrees_on_a_feature_branch(tmp_path):
    """A task whose verification needs a file that exists only on a WIP
    branch must be worked from that branch, not the default branch."""
    repo = init_repo(tmp_path / "wip", files={"base.txt": "on main\n"})
    subprocess.run(["git", "checkout", "-q", "-b", "feat/wip"], cwd=repo, check=True)
    (repo / "only_on_feat.py").write_text("VALUE = 0\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_feat.py").write_text(
        "from only_on_feat import VALUE\n\ndef test_v():\n    assert VALUE == 42\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "wip work"], cwd=repo, check=True)
    subprocess.run(
        ["git", "checkout", "-q", "main"], cwd=repo, check=True
    )  # default branch is behind

    state.save_task_store(
        repo,
        TaskGraph(
            [
                Task(
                    id="W-1",
                    title="set VALUE",
                    status="READY",
                    acceptance=["VALUE==42"],
                    verification=["python -m pytest tests/test_feat.py -q"],
                    files_hint=["only_on_feat.py"],
                ),
            ]
        ),
    )
    w = ScriptedWorker(
        "claude",
        {
            ("W-1", "implement"): lambda cwd: (cwd / "only_on_feat.py").write_text(
                "VALUE = 42\n", encoding="utf-8"
            ),
        },
    )

    # without --base: worktree off main, file absent -> BLOCKED
    r_main = engine.run(
        repo=repo, prompt_text=None, implement_workers=[w], only_task_ids={"W-1"}
    )
    assert r_main.task_outcomes[0].status == "BLOCKED"

    state.save_task_store(
        repo,
        TaskGraph(
            [
                Task(
                    id="W-1",
                    title="set VALUE",
                    status="READY",
                    acceptance=["VALUE==42"],
                    verification=["python -m pytest tests/test_feat.py -q"],
                    files_hint=["only_on_feat.py"],
                ),
            ]
        ),
    )
    r_feat = engine.run(
        repo=repo,
        prompt_text=None,
        implement_workers=[w],
        only_task_ids={"W-1"},
        base_ref="feat/wip",
    )
    assert r_feat.task_outcomes[0].status == "DONE"
    assert r_feat.verdict.result_status.value == "READY_FOR_REVIEW"
    assert git.current_branch(repo) == "main"  # protected branch untouched


def test_run_pauses_cleanly_on_a_reconcile_session_limit(demo_repo, monkeypatch):
    """A reconcile that fails on a usage limit makes the run finish
    BLOCKED_SESSION_LIMIT with a reset hint -- not raise, not run tasks."""
    from orchestrator import reconcile as reconcile_mod

    def boom(**kw):
        raise reconcile_mod.ReconciliationError(
            "could not reconcile prompt after 2 attempts: "
            "You've hit your session limit -- resets 2:40pm (Europe/Rome)"
        )

    monkeypatch.setattr(reconcile_mod, "reconcile", boom)

    w = ScriptedWorker("claude", {})
    result = engine.run(
        repo=demo_repo, prompt_text="do something", implement_workers=[w]
    )

    assert result.run_status == "BLOCKED_SESSION_LIMIT"
    assert result.session_limit_hint and "2:40pm" in result.session_limit_hint
    assert result.manifest.status == "BLOCKED_SESSION_LIMIT"
    assert result.task_outcomes == []
    assert "PAUSED" in result.run_paths.verdict.read_text(encoding="utf-8")
    assert not w.calls  # no task work started


def test_run_reconcile_error_that_is_not_a_limit_still_raises(demo_repo, monkeypatch):
    from orchestrator import reconcile as reconcile_mod

    def boom(**kw):
        raise reconcile_mod.ReconciliationError(
            "could not reconcile prompt after 2 attempts: bad JSON"
        )

    monkeypatch.setattr(reconcile_mod, "reconcile", boom)
    with pytest.raises(reconcile_mod.ReconciliationError):
        engine.run(
            repo=demo_repo,
            prompt_text="x",
            implement_workers=[ScriptedWorker("claude", {})],
        )


def test_run_resume_continues_from_the_task_store_and_links_the_prior_run(tmp_path):
    repo = init_repo(
        tmp_path / "res",
        files={
            "a.py": "x = 0\n",
            "b.py": "x = 0\n",
            "tests/test_a.py": "import sys,pathlib\nsys.path.insert(0,str(pathlib.Path(__file__).parents[1]))\n"
            "from a import x\n\ndef test_a():\n    assert x == 1\n",
            "tests/test_b.py": "import sys,pathlib\nsys.path.insert(0,str(pathlib.Path(__file__).parents[1]))\n"
            "from b import x\n\ndef test_b():\n    assert x == 1\n",
            "docs/PLAN.md": (
                "---\nproject: res\ncurrent_version: 0.0.0\ntarget_version: 0.1.0\n"
                "active_milestone: m\nstatus: IN_PROGRESS\n---\n# PROJECT PLAN\n\n## Tasks\n\n_x_\n"
            ),
        },
    )
    state.save_task_store(
        repo,
        TaskGraph(
            [
                Task(
                    id="RS-1",
                    title="a",
                    status="READY",
                    verification=["python -m pytest tests/test_a.py -q"],
                    files_hint=["a.py"],
                ),
                Task(
                    id="RS-2",
                    title="b",
                    status="READY",
                    verification=["python -m pytest tests/test_b.py -q"],
                    files_hint=["b.py"],
                ),
            ]
        ),
    )

    # run 1: only RS-1, it succeeds
    w1 = ScriptedWorker(
        "claude",
        {
            ("RS-1", "implement"): lambda cwd: (cwd / "a.py").write_text(
                "x = 1\n", encoding="utf-8"
            )
        },
    )
    r1 = engine.run(
        repo=repo, prompt_text=None, implement_workers=[w1], only_task_ids={"RS-1"}
    )
    assert r1.task_outcomes[0].status == "DONE"
    run1_id = r1.run_paths.run_id
    run1_plan_before = r1.run_paths.plan_before.read_text(encoding="utf-8")

    # unknown resume id errors
    with pytest.raises(ValueError, match="no run"):
        engine.run(
            repo=repo, prompt_text=None, implement_workers=[w1], resume_from="nope-123"
        )

    # run 2: resume -- RS-1 already DONE, only RS-2 runs; prior plan carried forward
    w2 = ScriptedWorker(
        "claude",
        {
            ("RS-2", "implement"): lambda cwd: (cwd / "b.py").write_text(
                "x = 1\n", encoding="utf-8"
            )
        },
    )
    r2 = engine.run(
        repo=repo,
        prompt_text="ignored on resume",
        implement_workers=[w2],
        resume_from=run1_id,
    )
    assert [o.task_id for o in r2.task_outcomes] == ["RS-2"]
    assert r2.task_outcomes[0].status == "DONE"
    assert r2.manifest.resumed_from == run1_id
    assert "resumed from run" in r2.manifest.notes
    assert r2.run_paths.plan_before.read_text(encoding="utf-8") == run1_plan_before
    assert r2.run_paths.run_id != run1_id


def test_run_warns_about_tasks_that_touch_the_same_file(tmp_path):
    from orchestrator import extensions

    repo = init_repo(tmp_path / "ov")
    state.save_task_store(
        repo,
        TaskGraph(
            [
                Task(
                    id="OV-1",
                    title="a",
                    status="READY",
                    verification=['python -c "pass"'],
                    files_hint=["./m.py"],
                ),
                Task(
                    id="OV-2",
                    title="b",
                    status="READY",
                    verification=['python -c "pass"'],
                    files_hint=["m.py"],
                ),
            ]
        ),
    )
    seen = []
    extensions.register_hook(
        "possible_overlap",
        lambda **kw: seen.append((kw["task_a"], kw["task_b"], kw["path"])),
    )

    engine.run(
        repo=repo, prompt_text=None, implement_workers=[ScriptedWorker("claude", {})]
    )
    assert ("OV-1", "OV-2", "m.py") in seen


def test_task_that_never_gets_fixed_is_blocked(demo_repo):
    repo = demo_repo
    graph = TaskGraph(
        [
            Task(
                id="TEST-003",
                title="Implement mul() badly forever",
                status="READY",
                acceptance=["mul(2, 3) == 6"],
                verification=["python -m pytest tests/test_mul.py -q"],
                files_hint=["mul_mod.py"],
            )
        ]
    )
    state.save_task_store(repo, graph)

    stubborn = ScriptedWorker("codex", {("TEST-003", "implement"): write_wrong_mul})
    # no fix ever supplied for debug stage -> stays wrong every attempt

    result = engine.run(
        repo=repo, prompt_text=None, implement_workers=[stubborn], max_debug_attempts=2
    )
    outcome = result.task_outcomes[0]
    assert outcome.status == "BLOCKED"
    assert outcome.debug_attempts == 2
    assert "exhausted 2 debug attempts" in outcome.reason
    assert result.plan.meta.status.value == "BLOCKED"


def test_passing_task_requires_independent_review_and_persists_evidence(demo_repo):
    task = Task(
        id="REV-001",
        title="implement add correctly",
        status="READY",
        acceptance=["add(2, 3) == 5"],
        verification=["python -m pytest tests/test_add.py -q"],
        files_hint=["add_mod.py"],
    )
    state.save_task_store(demo_repo, TaskGraph([task]))
    implementer = ScriptedWorker("codex", {("REV-001", "implement"): write_correct_add})
    reviewer = ScriptedWorker("claude", {})

    result = engine.run(
        repo=demo_repo,
        prompt_text=None,
        implement_workers=[implementer],
        review_workers=[reviewer],
    )

    outcome = result.task_outcomes[0]
    assert outcome.status == "DONE"
    assert outcome.reviewer == "claude"
    assert reviewer.calls == [("REV-001", "review")]
    assert (result.run_paths.evidence_dir / "REV-001.review-1.json").exists()


def test_requested_review_changes_are_repaired_reverified_and_rereviewed(demo_repo):
    task = Task(
        id="REV-002",
        title="implement add generally",
        status="READY",
        acceptance=["add works for arbitrary integers"],
        verification=["python -m pytest tests/test_add.py -q"],
        files_hint=["add_mod.py"],
    )
    state.save_task_store(demo_repo, TaskGraph([task]))
    implementer = ScriptedWorker(
        "codex",
        {
            ("REV-002", "implement"): lambda cwd: (cwd / "add_mod.py").write_text(
                "def add(a, b):\n    return 5\n", encoding="utf-8"
            )
        },
    )
    repairer = ScriptedWorker("opencode", {("REV-002", "debug"): write_correct_add})
    reviewer = SequencedReviewWorker(
        "claude", ["REQUEST_CHANGES\n- do not hard-code 5", "APPROVE"]
    )

    result = engine.run(
        repo=demo_repo,
        prompt_text=None,
        implement_workers=[implementer],
        debug_workers=[repairer],
        review_workers=[reviewer],
        max_review_repair_attempts=1,
    )

    outcome = result.task_outcomes[0]
    assert outcome.status == "DONE"
    assert reviewer.calls == [("REV-002", "review"), ("REV-002", "review")]
    assert repairer.calls == [("REV-002", "debug")]
    assert (result.run_paths.evidence_dir / "REV-002.review-2.json").exists()


def test_unresolved_review_is_blocked_when_repair_limit_is_reached(demo_repo):
    task = Task(
        id="REV-003",
        title="review must be accepted",
        status="READY",
        acceptance=["implementation is accepted"],
        verification=["python -m pytest tests/test_add.py -q"],
        files_hint=["add_mod.py"],
    )
    state.save_task_store(demo_repo, TaskGraph([task]))
    implementer = ScriptedWorker("codex", {("REV-003", "implement"): write_correct_add})
    reviewer = SequencedReviewWorker(
        "claude", ["REQUEST_CHANGES\n- add a boundary test"]
    )

    result = engine.run(
        repo=demo_repo,
        prompt_text=None,
        implement_workers=[implementer],
        review_workers=[reviewer],
        max_review_repair_attempts=0,
    )

    outcome = result.task_outcomes[0]
    assert outcome.status == "BLOCKED"
    assert outcome.reason == "review repair limit reached"
    assert outcome.review_verdict == "REQUEST_CHANGES"


class ReconcileOnlyWorker(Worker):
    """Returns a valid reconcile JSON with zero tasks -- the 'request already
    satisfied' case."""

    name = "recon"

    def __init__(self, tasks_json="[]"):
        self._tasks_json = tasks_json

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        payload = (
            '{"classification": "NEW_REQUIREMENT", '
            '"change_history_entry": "Already done.", '
            f'"tasks": {self._tasks_json}}}'
        )
        return WorkerResponse(
            ok=True,
            summary=payload,
            raw_output=payload,
            duration_seconds=0.02,
            worker=self.name,
            cost_usd=0.003,
            extra={
                "usage": {
                    "input_tokens": 4000,
                    "output_tokens": 120,
                    "cache_read_tokens": 0,
                }
            },
        )


def test_run_with_nothing_to_do_is_not_blocked(demo_repo):
    repo = demo_repo
    result = engine.run(
        repo=repo,
        prompt_text="please do the thing that is already done",
        implement_workers=[ReconcileOnlyWorker()],
    )
    assert result.nothing_to_do is True
    assert result.task_outcomes == []
    assert result.manifest.status == "NO_WORK"
    assert result.plan.meta.status.value != "BLOCKED"
    # reconcile call is now persisted as evidence and shows up in the cost total
    assert (result.run_paths.evidence_dir / "reconcile.reconcile.json").exists()
    assert result.usage["totals"]["cost_usd"] == 0.003
    assert result.usage["by_stage"]["reconcile"]["input_tokens"] == 4000
    assert "NO WORK" in result.run_paths.verdict.read_text(encoding="utf-8")


def test_status_reports_without_executing(demo_repo):
    repo = demo_repo
    _seed_tasks(repo)
    s = engine.status(repo)
    assert s["total_tasks"] == 2
    assert s["tasks_by_status"]["READY"] == 2
