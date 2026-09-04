import pytest

from orchestrator.executor import ExecutionPolicy, ExecutorError, LocalExecutor


def test_executor_rejects_commands_outside_allowed_workspace(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    executor = LocalExecutor(ExecutionPolicy(allowed_roots=[allowed]))

    with pytest.raises(ExecutorError, match="outside"):
        executor.validate_cwd(tmp_path / "other")


def test_read_only_executor_rejects_declared_write_operation(tmp_path):
    executor = LocalExecutor(ExecutionPolicy(allowed_roots=[tmp_path], read_only=True))

    with pytest.raises(ExecutorError, match="read-only"):
        executor.run("python -c \"print('x')\"", cwd=tmp_path, writes=True)
