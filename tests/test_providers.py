"""Tests for tinyagentos/providers/__init__.py.

Verifies that every backend type is consistently registered across
ALL_TYPES, CLOUD_TYPES/LOCAL_TYPES, BACKEND_TYPE_MAP, and
NEEDS_API_BASE_TYPES — the four lookup structures that routing,
litellm_config, and the frontend all consume.
"""
from __future__ import annotations

import pytest

from tinyagentos.providers import (
    ALL_TYPES,
    BACKEND_TYPE_MAP,
    CHAT_BACKEND_TYPE_MAP,
    CLOUD_TYPES,
    LOCAL_TYPES,
    NEEDS_API_BASE_TYPES,
)


class TestTypeSets:
    """Cross-consistency of the type sets."""

    def test_local_types_is_all_minus_cloud(self):
        assert LOCAL_TYPES == ALL_TYPES - CLOUD_TYPES

    def test_lmstudio_in_all_types(self):
        assert "lmstudio" in ALL_TYPES

    def test_lmstudio_not_cloud(self):
        assert "lmstudio" not in CLOUD_TYPES

    def test_lmstudio_is_local(self):
        assert "lmstudio" in LOCAL_TYPES

    def test_lmstudio_needs_api_base(self):
        assert "lmstudio" in NEEDS_API_BASE_TYPES


class TestBackendTypeMap:
    """LiteLLM prefix mappings."""

    def test_lmstudio_maps_to_openai(self):
        assert BACKEND_TYPE_MAP["lmstudio"] == "openai"

    def test_lmstudio_chat_map_inherits(self):
        # CHAT_BACKEND_TYPE_MAP spreads BACKEND_TYPE_MAP
        assert CHAT_BACKEND_TYPE_MAP["lmstudio"] == "openai"

    def test_every_type_has_litellm_prefix(self):
        from tinyagentos.providers import IMAGE_GEN_TYPES

        for t in ALL_TYPES:
            if t in IMAGE_GEN_TYPES:
                continue  # image-gen types have no LiteLLM chat prefix
            assert t in BACKEND_TYPE_MAP, f"missing BACKEND_TYPE_MAP entry for {t}"

    def test_cloud_types_not_in_needs_api_base(self):
        for t in CLOUD_TYPES:
            if t != "openai-compatible":
                assert t not in NEEDS_API_BASE_TYPES, (
                    f"cloud type {t} should not be in NEEDS_API_BASE_TYPES"
                )
