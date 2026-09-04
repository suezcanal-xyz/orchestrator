from orchestrator.debugger import classify_failure, run_debug_loop
from orchestrator.task_graph import Task
from orchestrator.verifier import VerificationResult
from orchestrator.workers.base import Worker, WorkerResponse


class FakeWorker(Worker):
    """A worker double that never shells out -- pure Python, for tests."""

    def __init__(self, name: str, summaries: list[str]):
        self.name = name
        self._summaries = summaries
        self._calls = 0

    def _invoke(self, cwd, prompt, *, timeout, allow_edit, structured=False):
        summary = self._summaries[min(self._calls, len(self._summaries) - 1)]
        self._calls += 1
        return WorkerResponse(
            ok=True,
            summary=summary,
            raw_output=summary,
            duration_seconds=0.01,
            worker=self.name,
        )


def make_task():
    return Task(
        id="SC-001",
        title="Fix geolocation",
        status="IN_PROGRESS",
        acceptance=["coordinates resolve"],
        verification=['python -c "1"'],
    )


def _fail_result(msg="AssertionError: coords wrong"):
    return VerificationResult(
        command="pytest tests/x", exit_code=1, passed=False, stderr=msg
    )


def _pass_result():
    return VerificationResult(command="pytest tests/x", exit_code=0, passed=True)


def test_classify_failure_matches_assertion():
    assert (
        classify_failure([_fail_result("AssertionError: boom")]) == "ASSERTION_FAILURE"
    )


def test_classify_failure_matches_import_error():
    assert (
        classify_failure([_fail_result("ModuleNotFoundError: no module named x")])
        == "MISSING_DEPENDENCY_OR_IMPORT"
    )


def test_classify_failure_unknown_default():
    assert (
        classify_failure([_fail_result("something bizarre happened")])
        == "UNKNOWN_FAILURE"
    )


def test_debug_loop_returns_fixed_immediately_if_already_passing(tmp_path):
    outcome = run_debug_loop(
        cwd=tmp_path,
        task=make_task(),
        initial_results=[_pass_result()],
        verification_commands=["pytest tests/x"],
        debugger_workers=[FakeWorker("claude", ["n/a"])],
        run_verification_fn=lambda: [_pass_result()],
        get_diff_fn=lambda: "",
        commit_fn=lambda msg: "deadbeef",
    )
    assert outcome.status == "FIXED"
    assert outcome.attempts == []


def test_debug_loop_fixes_on_second_attempt_and_alternates_workers(tmp_path):
    call_log = []
    results_sequence = [[_fail_result()], [_pass_result()]]
    call_count = {"n": 0}

    def run_verification_fn():
        r = results_sequence[min(call_count["n"], len(results_sequence) - 1)]
        call_count["n"] += 1
        return r

    def commit_fn(msg):
        call_log.append(msg)
        return "sha" + str(len(call_log))

    outcome = run_debug_loop(
        cwd=tmp_path,
        task=make_task(),
        initial_results=[_fail_result()],
        verification_commands=["pytest tests/x"],
        debugger_workers=[
            FakeWorker("claude", ["diagnosis 1"]),
            FakeWorker("codex", ["fix applied"]),
        ],
        run_verification_fn=run_verification_fn,
        get_diff_fn=lambda: "diff --git a b",
        commit_fn=commit_fn,
    )
    assert outcome.status == "FIXED"
    assert len(outcome.attempts) == 2
    assert outcome.attempts[0].debugger_worker == "claude"
    assert outcome.attempts[1].debugger_worker == "codex"
    assert len(call_log) == 2


def test_debug_loop_blocks_after_max_attempts(tmp_path):
    outcome = run_debug_loop(
        cwd=tmp_path,
        task=make_task(),
        initial_results=[_fail_result()],
        verification_commands=["pytest tests/x"],
        debugger_workers=[FakeWorker("claude", ["still broken"])],
        run_verification_fn=lambda: [_fail_result()],
        get_diff_fn=lambda: "",
        commit_fn=lambda msg: None,
        max_attempts=3,
    )
    assert outcome.status == "BLOCKED"
    assert len(outcome.attempts) == 3
    assert "exhausted 3 debug attempts" in outcome.reason


def test_debug_loop_blocked_without_workers(tmp_path):
    outcome = run_debug_loop(
        cwd=tmp_path,
        task=make_task(),
        initial_results=[_fail_result()],
        verification_commands=["pytest tests/x"],
        debugger_workers=[],
        run_verification_fn=lambda: [_fail_result()],
        get_diff_fn=lambda: "",
        commit_fn=lambda msg: None,
    )
    assert outcome.status == "BLOCKED"
    assert outcome.attempts == []
