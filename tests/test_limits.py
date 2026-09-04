from orchestrator.limits import session_limit_hint


def test_detects_claude_session_limit_with_reset_time():
    hint = session_limit_hint(
        "Error: You've hit your session limit -- resets 2:40pm (Europe/Rome)"
    )
    assert hint and "2:40pm" in hint


def test_detects_usage_limit_without_a_reset_time():
    assert session_limit_hint("usage limit reached") == "unknown"
    assert session_limit_hint("You have reached your weekly limit") == "unknown"


def test_detects_429_and_retry_after():
    hint = session_limit_hint("HTTP 429 Too Many Requests; retry-after: 60s")
    assert hint and "60s" in hint


def test_ignores_ordinary_errors():
    assert session_limit_hint("ModuleNotFoundError: no module named foo") is None
    assert session_limit_hint("assertion failed: 1 != 2", "") is None
    assert session_limit_hint(None) is None


def test_first_matching_text_wins():
    assert (
        session_limit_hint(None, "", "quota exceeded, reset after midnight")
        == "midnight"
    )
