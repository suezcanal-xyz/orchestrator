import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from calc import add, multiply, subtract


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_multiply():
    assert multiply(4, 3) == 12
