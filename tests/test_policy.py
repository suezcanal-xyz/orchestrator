from orchestrator import extensions, policy


def setup_function():
    extensions.reset_extensions()


def teardown_function():
    extensions.reset_extensions()


def test_effective_workers_default_when_nothing_set():
    assert policy.effective_workers("demo", ()) == list(policy.DEFAULT_IMPLEMENT_WORKERS)
    assert policy.effective_workers(None, None) == list(policy.DEFAULT_IMPLEMENT_WORKERS)


def test_effective_workers_cli_wins_over_policy():
    extensions.register_policy("workers", lambda project, stage="implement": ["codex"])
    assert policy.effective_workers("demo", ("claude", "opencode")) == ["claude", "opencode"]


def test_effective_workers_uses_policy_when_no_cli_flag():
    extensions.register_policy(
        "workers",
        lambda project, stage="implement": ["codex", "claude"] if project == "seacommons" else ["claude"],
    )
    assert policy.effective_workers("seacommons", ()) == ["codex", "claude"]
    assert policy.effective_workers("other", ()) == ["claude"]


def test_effective_workers_tolerates_one_arg_policy():
    extensions.register_policy("workers", lambda project: ["opencode"])
    assert policy.effective_workers("demo", ()) == ["opencode"]


def test_effective_workers_stage_is_passed_through():
    seen = {}

    def pol(project, stage="implement"):
        seen["stage"] = stage
        return ["claude"]

    extensions.register_policy("workers", pol)
    policy.effective_workers("demo", (), stage="debug")
    assert seen["stage"] == "debug"


def test_effective_int_precedence():
    assert policy.effective_int("max_debug_attempts", "demo", 3) == 3
    extensions.register_policy("max_debug_attempts", lambda project: 5)
    assert policy.effective_int("max_debug_attempts", "demo", 3) == 5
    assert policy.effective_int("max_debug_attempts", "demo", 3, cli_value=1) == 1
