"""A tiny, deliberately incomplete calculator module.

add() works. subtract() and multiply() are the gap this example repository
exists to demonstrate the orchestrator closing.
"""


def add(a: int, b: int) -> int:
    return a + b


def subtract(a: int, b: int) -> int:
    raise NotImplementedError("subtract is not implemented yet")


def multiply(a: int, b: int) -> int:
    # intentional bug for the debug loop to catch and fix
    return a + b
