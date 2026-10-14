"""Bootstrap tests for LIFECORE-SWE core functionality."""

from lifecore_swe.core import add


def test_add():
    """Verify that add function correctly computes the sum of two integers."""
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0
