"""Route-level tests for POST /api/agent-model-keys (mint) — agent_id validation.

The mint endpoint must reject agent_ids that contain path traversal characters
before they ever reach the store, regardless of authentication.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _ensure_agent_model_key_store(client, tmp_path_factory):
    """Init app.state.agent_model_keys on a fresh DB; the test client registers
    the store but does not run the lifespan that init()s it (production does)."""
    store = client._transport.app.state.agent_model_keys
    if store._db is not None:
        try:
            asyncio.get_event_loop().run_until_complete(store.close())
        except Exception:
            pass
    tmp_dir = tmp_path_factory.mktemp("agent_model_keys_route_test")
    store.db_path = tmp_dir / "agent_model_keys.db"
    asyncio.get_event_loop().run_until_complete(store.init())
    yield
    try:
        asyncio.get_event_loop().run_until_complete(store.close())
    except Exception:
        pass


@pytest.mark.asyncio
class TestAgentModelKeysRouteValidation:
    """Route-level input validation for POST /api/agent-model-keys."""

    @pytest.mark.parametrize(
        "agent_ids",
        [
            ["../../x"],
            ["a/b"],
            ["openai/gpt-4o"],       # real-world LiteLLM model name with /
            ["a\\b"],
            ["/etc/passwd"],
            ["valid", "../../escape"],
            ["a b"],
            [""],
        ],
    )
    async def test_mint_rejects_unsafe_agent_ids(self, client, agent_ids):
        """Pydantic field_validator must reject path traversal before the store."""
        resp = await client.post(
            "/api/agent-model-keys",
            json={"agent_ids": agent_ids},
        )
        # FastAPI returns 422 for Pydantic validation failures.
        assert resp.status_code == 422, (
            f"expected 422 for agent_ids={agent_ids!r}, "
            f"got {resp.status_code}: {resp.text}"
        )

    async def test_mint_allows_safe_agent_ids(self, client):
        """Valid slug-format agent ids pass Pydantic validation (the store is
        reached — a store-init error proves validation passed the 422 gate).
        """
        resp = await client.post(
            "/api/agent-model-keys",
            json={"agent_ids": ["safe-agent-1", "gpt_4o.test"]},
        )
        # The store is not initialised in the default conftest client, so we
        # expect 500 (store error), NOT 422 (validation rejection).  A 422
        # here would mean the regex is too strict and safe slugs are blocked.
        assert resp.status_code != 422, (
            f"safe slugs should not be rejected by validation, "
            f"got {resp.status_code}: {resp.text}"
        )

    async def test_mint_rejects_empty_agent_ids(self, client):
        """Empty list is rejected."""
        resp = await client.post(
            "/api/agent-model-keys",
            json={"agent_ids": []},
        )
        assert resp.status_code == 422
