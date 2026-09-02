from orchestrator import extensions
from orchestrator.doctor import DoctorEntry, format_report


def setup_function(fn):
    extensions.reset_extensions()


def teardown_function(fn):
    extensions.reset_extensions()


def test_format_report_not_found():
    report = format_report([DoctorEntry("ghost", False, None, False, "not found on PATH")])
    assert "ghost" in report
    assert "NOT FOUND" in report


def test_format_report_found_with_worker():
    e = DoctorEntry("codex", True, "/usr/bin/codex", True, "Logged in using ChatGPT")
    report = format_report([e])
    assert "found" in report
    assert "Logged in" in report
    assert "worker available" in report


def test_format_report_found_without_worker():
    e = DoctorEntry("opencode", True, "/usr/bin/opencode", False, "not authenticated")
    report = format_report([e])
    assert "NO WORKER REGISTERED" in report


def test_worker_registered_reflects_extensions_registry():
    from orchestrator.doctor import _worker_registered

    assert _worker_registered("codex") is True  # builtin
    assert _worker_registered("claude") is True  # builtin
    assert _worker_registered("opencode") is True  # builtin since v0.2.0
    assert _worker_registered("totally-unknown-cli") is False
    extensions.register_worker("totally-unknown-cli", lambda: None)
    assert _worker_registered("totally-unknown-cli") is True
