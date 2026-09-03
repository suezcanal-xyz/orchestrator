from orchestrator import verifier


def test_passing_command(tmp_path):
    r = verifier.run_command("python -c \"print(1)\"", tmp_path)
    assert r.passed
    assert r.exit_code == 0
    assert "1" in r.stdout


def test_failing_command(tmp_path):
    r = verifier.run_command("python -c \"import sys; sys.exit(3)\"", tmp_path)
    assert not r.passed
    assert r.exit_code == 3


def test_run_verification_collects_all_by_default(tmp_path):
    results = verifier.run_verification(
        ["python -c \"import sys; sys.exit(1)\"", "python -c \"print(2)\""], tmp_path
    )
    assert len(results) == 2
    assert not verifier.overall_passed(results)
    assert len(verifier.failing(results)) == 1


def test_stop_on_first_failure(tmp_path):
    results = verifier.run_verification(
        ["python -c \"import sys; sys.exit(1)\"", "python -c \"print(2)\""],
        tmp_path,
        stop_on_first_failure=True,
    )
    assert len(results) == 1


def test_overall_passed_empty_is_false(tmp_path):
    assert verifier.overall_passed([]) is False


def test_timeout_is_captured_not_raised(tmp_path):
    r = verifier.run_command("python -c \"import time; time.sleep(5)\"", tmp_path, timeout=1)
    assert not r.passed
    assert r.exit_code == 124
    assert "timed out" in r.stderr


def test_python_command_leaves_no_pycache(tmp_path):
    """A verification command must only report pass/fail -- it must not
    leave __pycache__/ behind for the next `git add -A` (debugger.py's
    commit_fn) to pick up as unrelated evidence-diff noise (see the
    _VERIFICATION_ENV comment in verifier.py)."""
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    r = verifier.run_command("python -c \"import mod; assert mod.f() == 1\"", tmp_path)
    assert r.passed
    assert not (tmp_path / "__pycache__").exists()
