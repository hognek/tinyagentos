"""Tests for the approve-path grant expiry: duration_secs -> expires_at.

Two layers are asserted here, because the wiring is what #2985 was actually
missing:

* ``TestExpiresAtFromDuration`` — the pure mapping (positive int -> future
  timezone-aware ISO, anything else -> None), unit-level.
* ``TestApprovePathWiresExpiry`` — the *route-level* mapping: a pending request
  carrying ``duration_secs`` must end up with that expiry persisted on the
  granted scope after approval, and a request without it must stay unbounded.
  These drive the real approve machinery (``approve_request_record`` via the
  HTTP route) against a real ``AgentGrantsStore``, so they fail if the
  ``expires_at=expires_at`` argument is dropped from either ``add_grant`` call
  site. The store-level persistence itself is covered by
  ``tests/test_agent_grants_store.py``.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tinyagentos.routes.agent_auth_requests import _expires_at_from_duration


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


class TestExpiresAtFromDuration:
    def test_positive_duration_yields_future_expiry(self):
        now = datetime.now(timezone.utc)
        expires = _expires_at_from_duration(3600)
        assert expires is not None
        parsed = _parse(expires)
        assert parsed.tzinfo is not None, "expiry must be timezone-aware"
        delta = parsed - now
        # allow a small clock skew window around the intended 1 hour
        assert timedelta(minutes=59) < delta <= timedelta(hours=1, minutes=1)

    def test_none_duration_is_unbounded(self):
        assert _expires_at_from_duration(None) is None

    def test_zero_duration_is_unbounded(self):
        assert _expires_at_from_duration(0) is None

    def test_negative_duration_is_unbounded(self):
        assert _expires_at_from_duration(-60) is None

    def test_non_int_duration_is_unbounded(self):
        # a float or string must not produce a bogus expiry
        assert _expires_at_from_duration(3660.5) is None
        assert _expires_at_from_duration("3600") is None

    def test_short_duration_still_in_the_future(self):
        expires = _expires_at_from_duration(30)
        assert expires is not None
        parsed = _parse(expires)
        assert parsed > datetime.now(timezone.utc) - timedelta(seconds=1)


class TestApprovePathWiresExpiry:
    """The route-level mapping #2985 exists to add: approving a request must
    persist its duration_secs as a real future expires_at on the grant. These
    tests drive the HTTP approve route against a real store, so they are the
    red that fails when the `expires_at=` wiring is removed from add_grant."""

    async def _approve(self, client, monkeypatch, tmp_path, duration_secs):
        from tinyagentos.agent_registry_store import (
            AgentRegistryStore,
            load_or_create_signing_keypair,
        )
        from tinyagentos.auth_requests_store import AuthRequestsStore
        from tinyagentos.agent_grants_store import AgentGrantsStore

        registry = AgentRegistryStore(tmp_path / "reg.db")
        await registry.init()
        auth_store = AuthRequestsStore(tmp_path / "auth.db")
        await auth_store.init()
        grants = AgentGrantsStore(tmp_path / "grants.db")
        await grants.init()
        priv, pub = load_or_create_signing_keypair(tmp_path / "keys")

        # A global, non-project scope keeps the approve path simple (no
        # project_id binding or membership sync needed).
        rec = await auth_store.create(
            identity_claim="@expiry-agent", framework="openclaw",
            requested_scopes=["registry_feeds_read"], requested_skills=None, reason="",
            duration_secs=duration_secs, project_id=None,
        )
        monkeypatch.setattr(client._transport.app.state, "agent_registry", registry)
        monkeypatch.setattr(client._transport.app.state, "auth_requests", auth_store)
        monkeypatch.setattr(client._transport.app.state, "agent_grants", grants)
        monkeypatch.setattr(client._transport.app.state, "agent_registry_keypair", (priv, pub))

        resp = await client.post(
            f"/api/agents/auth-requests/{rec['id']}/approve",
            json={"granted_scopes": ["registry_feeds_read"]},
        )
        assert resp.status_code == 200, resp.text
        cid = resp.json()["canonical_id"]

        agent_grants = await grants.list_grants(cid)
        scoped = [g for g in agent_grants if g["scope"] == "registry_feeds_read"]
        assert len(scoped) == 1, f"expected one registry_feeds_read grant, got {agent_grants}"
        expiry = scoped[0].get("expires_at")

        await registry.close()
        await auth_store.close()
        await grants.close()
        return expiry

    @pytest.mark.asyncio
    async def test_duration_secs_persists_future_expiry_on_grant(
        self, client, monkeypatch, tmp_path
    ):
        expiry = await self._approve(client, monkeypatch, tmp_path, 3600)
        assert expiry is not None, "grant must carry a future expiry when duration_secs was set"
        parsed = _parse(expiry)
        assert parsed.tzinfo is not None, "persisted expiry must be timezone-aware"
        delta = parsed - datetime.now(timezone.utc)
        assert timedelta(minutes=59) < delta <= timedelta(hours=1, minutes=1)

    @pytest.mark.asyncio
    async def test_missing_duration_stays_unbounded(
        self, client, monkeypatch, tmp_path
    ):
        expiry = await self._approve(client, monkeypatch, tmp_path, None)
        assert expiry is None, "grant must stay unbounded when duration_secs is absent"


class TestReusePathWiresExpiry:
    """The third wiring site (jaylfc 2026-09-22 review): when an already-ACTIVE
    agent's handle collides and the approval is project-scoped, the reuse/ADD
    branch calls ``add_agent_to_project`` — which forwards ``expires_at`` into
    the *second* project's grant. Deleting ``expires_at=expires_at`` from that
    call leaves the rest of the suite green while this path silently reverts to
    unbounded grants. This test is the red that catches that wiring."""

    @pytest.mark.asyncio
    async def test_reused_identity_second_project_keeps_expiry(
        self, client, monkeypatch, tmp_path
    ):
        from tinyagentos.agent_registry_store import (
            AgentRegistryStore,
            load_or_create_signing_keypair,
        )
        from tinyagentos.auth_requests_store import AuthRequestsStore
        from tinyagentos.agent_grants_store import AgentGrantsStore
        from tinyagentos.projects.project_store import ProjectStore

        registry = AgentRegistryStore(tmp_path / "reg-rp.db")
        await registry.init()
        auth_store = AuthRequestsStore(tmp_path / "auth-rp.db")
        await auth_store.init()
        grants = AgentGrantsStore(tmp_path / "grants-rp.db")
        await grants.init()
        pstore = ProjectStore(tmp_path / "projects-rp.db")
        await pstore.init()
        priv, pub = load_or_create_signing_keypair(tmp_path / "keys-rp")

        pA = await pstore.create_project(name="A", slug="proj-a", created_by="u")
        pB = await pstore.create_project(name="B", slug="proj-b", created_by="u")

        monkeypatch.setattr(client._transport.app.state, "agent_registry", registry)
        monkeypatch.setattr(client._transport.app.state, "auth_requests", auth_store)
        monkeypatch.setattr(client._transport.app.state, "agent_grants", grants)
        monkeypatch.setattr(client._transport.app.state, "agent_registry_keypair", (priv, pub))
        monkeypatch.setattr(client._transport.app.state, "project_store", pstore)

        # Establish the active identity on project A (handle "taosmd-dev").
        rA = await auth_store.create(
            identity_claim="@taosmd-dev", framework="openclaw",
            requested_scopes=["project_tasks"], requested_skills=None, reason="",
            duration_secs=None, project_id=pA["id"],
        )
        respA = await client.post(
            f"/api/agents/auth-requests/{rA['id']}/approve",
            json={"granted_scopes": ["project_tasks"], "project_id": pA["id"]},
        )
        assert respA.status_code == 200, respA.text
        cid = respA.json()["canonical_id"]

        # Second request, same handle, project B, WITH a duration_secs. This must
        # reuse the identity (no 409) and the project-B grant must carry a real
        # future expiry — the exact wiring jaylfc's mutation test showed is
        # otherwise unasserted.
        rB = await auth_store.create(
            identity_claim="@taosmd-dev", framework="openclaw",
            requested_scopes=["project_tasks"], requested_skills=None, reason="",
            duration_secs=3600, project_id=pB["id"],
        )
        respB = await client.post(
            f"/api/agents/auth-requests/{rB['id']}/approve",
            json={"granted_scopes": ["project_tasks"], "project_id": pB["id"]},
        )
        assert respB.status_code == 200, respB.text
        assert respB.json()["canonical_id"] == cid

        agent_grants = await grants.list_grants(cid)
        prjB = [
            g for g in agent_grants
            if g.get("project_id") == pB["id"] and g["scope"] == "project_tasks"
        ]
        assert len(prjB) == 1, f"expected one project-B project_tasks grant, got {agent_grants}"
        expiry = prjB[0].get("expires_at")
        assert expiry is not None, (
            "project-B grant must carry a future expiry when duration_secs was set "
            "(expires_at dropped from the add_agent_to_project call?)"
        )
        parsed = _parse(expiry)
        assert parsed.tzinfo is not None, "persisted expiry must be timezone-aware"
        delta = parsed - datetime.now(timezone.utc)
        assert timedelta(minutes=59) < delta <= timedelta(hours=1, minutes=1)

        await registry.close()
        await auth_store.close()
        await grants.close()
        await pstore.close()
