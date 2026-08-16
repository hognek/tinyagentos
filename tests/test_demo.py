"""Demo test file for all-skip check."""

import pytest

# Test 1: importorskip on a module that doesn't exist - should skip
def test_placeholder_importorskip():
    """This test will skip because the module doesn't exist."""
    pytest.importorskip("nonexistent_module_12345")
    assert True

# Test 2: pytest.skip with a reason - should skip
def test_placeholder_skip():
    """This test will skip via pytest.skip."""
    pytest.skip("This module not available yet")
    assert True

# Test 3: A normal passing test - should pass
def test_actual_test():
    """A normal test that passes."""
    assert True
