"""Tests for AgentGrantsStore — per-agent scope grants persistence."""
import pytest

from tinyagentos.agent_grants_store import AgentGrantsStore


@pytest.mark.asyncio
class TestAgentGrantsStore:
    # ── helpers ──────────────────────────────────────────────────────
    async def _store(self, tmp_path):
        s = AgentGrantsStore(tmp_path / "grants.db")
        await s.init()
        return s

    # ── add_grant ────────────────────────────────────────────────────
    async def test_add_grant_returns_inserted_row(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            row = await store.add_grant("agent-x", "app.kv.read")
            assert row["canonical_id"] == "agent-x"
            assert row["scope"] == "app.kv.read"
            assert row["tier"] == "once"
            assert row["project_id"] is None
            assert row["expires_at"] is None
            assert "granted_at" in row
            assert isinstance(row["id"], int)
        finally:
            await store.close()

    async def test_add_grant_with_optional_fields(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            row = await store.add_grant(
                "agent-y",
                "app.net",
                tier="always",
                project_id="proj-1",
                expires_at="2030-01-01T00:00:00+00:00",
            )
            assert row["tier"] == "always"
            assert row["project_id"] == "proj-1"
            assert row["expires_at"] == "2030-01-01T00:00:00+00:00"
        finally:
            await store.close()

    async def test_add_grant_idempotent_replace(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            await store.add_grant("agent-z", "app.kv.write", tier="once")
            second = await store.add_grant("agent-z", "app.kv.write", tier="always")
            assert second["tier"] == "always"
            grants = await store.list_grants("agent-z")
            assert len(grants) == 1
            assert grants[0]["tier"] == "always"
        finally:
            await store.close()

    async def test_add_grant_uninitialised_raises_runtime_error(self, tmp_path):
        store = AgentGrantsStore(tmp_path / "grants.db")
        try:
            with pytest.raises(RuntimeError, match="not initialised"):
                await store.add_grant("agent-x", "app.kv.read")
        finally:
            await store.close()

    # ── list_grants ──────────────────────────────────────────────────
    async def test_list_grants_returns_all_for_canonical_id(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            await store.add_grant("agent-a", "app.kv.read")
            await store.add_grant("agent-a", "app.kv.write")
            grants = await store.list_grants("agent-a")
            assert len(grants) == 2
            assert {g["scope"] for g in grants} == {"app.kv.read", "app.kv.write"}
        finally:
            await store.close()

    async def test_list_grants_empty_for_unknown_canonical_id(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            grants = await store.list_grants("nonexistent")
            assert grants == []
        finally:
            await store.close()

    async def test_list_grants_scoped_by_canonical_id(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            await store.add_grant("agent-1", "app.kv.read")
            await store.add_grant("agent-2", "app.kv.read")
            g1 = await store.list_grants("agent-1")
            g2 = await store.list_grants("agent-2")
            assert len(g1) == 1
            assert len(g2) == 1
            assert g1[0]["canonical_id"] == "agent-1"
            assert g2[0]["canonical_id"] == "agent-2"
        finally:
            await store.close()

    async def test_list_grants_uninitialised_raises_runtime_error(self, tmp_path):
        store = AgentGrantsStore(tmp_path / "grants.db")
        try:
            with pytest.raises(RuntimeError, match="not initialised"):
                await store.list_grants("agent-x")
        finally:
            await store.close()

    # ── list_active_grants ───────────────────────────────────────────
    async def test_list_active_grants_returns_non_expired(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            await store.add_grant("agent-a", "app.kv.read")
            await store.add_grant(
                "agent-b",
                "app.net",
                expires_at="2030-01-01T00:00:00+00:00",
            )
            active = await store.list_active_grants()
            assert len(active) == 2
        finally:
            await store.close()

    async def test_list_active_grants_excludes_expired(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            await store.add_grant("agent-a", "app.kv.read")
            await store.add_grant(
                "agent-b",
                "app.net",
                expires_at="2000-01-01T00:00:00+00:00",
            )
            active = await store.list_active_grants()
            assert len(active) == 1
            assert active[0]["canonical_id"] == "agent-a"
        finally:
            await store.close()

    async def test_list_active_grants_empty_when_all_expired(self, tmp_path):
        store = await self._store(tmp_path)
        try:
            await store.add_grant(
                "agent-a",
                "app.kv.read",
                expires_at="2000-01-01T00:00:00+00:00",
            )
            active = await store.list_active_grants()
            assert active == []
        finally:
            await store.close()

    async def test_list_active_grants_uninitialised_raises_runtime_error(self, tmp_path):
        store = AgentGrantsStore(tmp_path / "grants.db")
        try:
            with pytest.raises(RuntimeError, match="not initialised"):
                await store.list_active_grants()
        finally:
            await store.close()
