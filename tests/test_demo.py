"""Demo test file for all-skip check - ALL tests skip."""

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
