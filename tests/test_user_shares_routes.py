"""Tests for the user-to-user resource sharing routes.

Covers:
  POST   /api/shares               — create share (idempotent, unknown user, self-share)
  GET    /api/shares               — list (out/in)
  DELETE /api/shares/{id}          — revoke (owner, not-found, non-owner)

Uses the conftest `client` fixture (admin-authenticated) with the user_shares
store initialised on app.state.
"""

from __future__ import annotations

import secrets

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def shares_client(client, tmp_data_dir):
    """Async client with user_shares store initialised + CSRF tokens, as admin."""
    from tinyagentos.user_shares_store import UserSharesStore

    app = client._transport.app

    # Init user_shares store if not already on app.state (idempotent).
    if getattr(app.state, "user_shares", None) is None:
        store = UserSharesStore(tmp_data_dir / "user_shares.db")
        await store.init()
        app.state.user_shares = store

    # Set CSRF token so mutating routes pass verify_csrf.
    csrf_token = secrets.token_hex(32)
    client.cookies["csrf_token"] = csrf_token
    client.headers["X-CSRF-Token"] = csrf_token

    # Ensure bob user exists (target for share tests) via invite flow.
    auth = app.state.auth
    if auth.find_user("bob") is None:
        invite_code = auth.add_user_invite("bob", "admin")
        auth.complete_invite("bob", invite_code, "Bob", "", "bobpass1")

    yield client

    if hasattr(app.state, "user_shares"):
        await app.state.user_shares.close()


@pytest_asyncio.fixture
async def bob_client(shares_client):
    """Async client authenticated as user 'bob' (non-admin, non-owner)."""
    app = shares_client._transport.app

    # Create bob user if not already present.
    bob = app.state.auth.find_user("bob")
    if bob is None:
        invite_code = app.state.auth.add_user_invite("bob", "admin")
        app.state.auth.complete_invite("bob", invite_code, "Bob", "", "bobpass1")

    bob_record = app.state.auth.find_user("bob")
    bob_uid = bob_record["id"]
    bob_token = app.state.auth.create_session(user_id=bob_uid, long_lived=True)

    csrf_token = secrets.token_hex(32)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"taos_session": bob_token, "csrf_token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestShareRoutes:

    # -- Create ----------------------------------------------------------

    async def test_create_share(self, shares_client):
        """POST /api/shares creates a share and returns the record."""
        resp = await shares_client.post(
            "/api/shares",
            json={
                "resource_type": "project",
                "resource_id": "proj-1",
                "to_username": "bob",
                "permission": "read",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resource_type"] == "project"
        assert data["resource_id"] == "proj-1"
        assert data["permission"] == "read"
        assert "id" in data
        assert "granted_at" in data

    async def test_create_share_unknown_username(self, shares_client):
        """POST /api/shares with unknown username returns 404."""
        resp = await shares_client.post(
            "/api/shares",
            json={
                "resource_type": "project",
                "resource_id": "proj-3",
                "to_username": "nosuchuser",
                "permission": "read",
            },
        )
        assert resp.status_code == 404
        assert "nosuchuser" in resp.json()["detail"]

    async def test_create_share_duplicate_idempotent(self, shares_client):
        """Re-sharing the same resource+target+permission is idempotent."""
        body = {
            "resource_type": "project",
            "resource_id": "proj-2",
            "to_username": "bob",
            "permission": "read",
        }
        r1 = await shares_client.post("/api/shares", json=body)
        assert r1.status_code == 200

        r2 = await shares_client.post("/api/shares", json=body)
        assert r2.status_code == 200

        # Verify only one share exists — no duplicates.
        resp = await shares_client.get("/api/shares?direction=out")
        assert resp.status_code == 200
        matching = [
            s for s in resp.json()
            if s["resource_id"] == "proj-2"
        ]
        assert len(matching) == 1

    async def test_create_share_to_self_rejected(self, shares_client):
        """POST /api/shares to yourself returns 400."""
        resp = await shares_client.post(
            "/api/shares",
            json={
                "resource_type": "project",
                "resource_id": "proj-4",
                "to_username": "admin",
                "permission": "read",
            },
        )
        assert resp.status_code == 400
        assert "yourself" in resp.json()["detail"]

    # -- List ------------------------------------------------------------

    async def test_list_outgoing_shares(self, shares_client):
        """GET /api/shares?direction=out lists shares owned by the user."""
        # Create two shares.
        for res_id in ("proj-list-out-1", "proj-list-out-2"):
            r = await shares_client.post(
                "/api/shares",
                json={
                    "resource_type": "project",
                    "resource_id": res_id,
                    "to_username": "bob",
                    "permission": "read",
                },
            )
            assert r.status_code == 200

        resp = await shares_client.get("/api/shares?direction=out")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        out_ids = [s["resource_id"] for s in data if s["resource_type"] == "project"]
        assert "proj-list-out-1" in out_ids
        assert "proj-list-out-2" in out_ids

    async def test_list_incoming_shares(self, shares_client, bob_client):
        """GET /api/shares?direction=in lists shares received by the user."""
        # Admin shares with bob.
        r = await shares_client.post(
            "/api/shares",
            json={
                "resource_type": "project",
                "resource_id": "proj-list-in",
                "to_username": "bob",
                "permission": "read",
            },
        )
        assert r.status_code == 200

        # Bob lists incoming shares.
        resp = await bob_client.get("/api/shares?direction=in")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        in_ids = [s["resource_id"] for s in data if s["resource_type"] == "project"]
        assert "proj-list-in" in in_ids

    # -- Revoke ----------------------------------------------------------

    async def test_revoke_share(self, shares_client):
        """DELETE /api/shares/{id} revokes the share (owner)."""
        r = await shares_client.post(
            "/api/shares",
            json={
                "resource_type": "project",
                "resource_id": "proj-revoke",
                "to_username": "bob",
                "permission": "read",
            },
        )
        assert r.status_code == 200
        share_id = r.json()["id"]

        resp = await shares_client.delete(f"/api/shares/{share_id}")
        assert resp.status_code == 200
        assert resp.json() == {"status": "revoked", "share_id": share_id}

        # Share no longer listed.
        out = await shares_client.get("/api/shares?direction=out")
        assert out.status_code == 200
        matching = [s for s in out.json() if s["id"] == share_id]
        assert len(matching) == 0

    async def test_revoke_nonexistent_share(self, shares_client):
        """DELETE /api/shares/{id} on non-existent share returns 404."""
        resp = await shares_client.delete("/api/shares/99999")
        assert resp.status_code == 404

    async def test_revoke_by_non_owner_unauthorized(self, shares_client, bob_client):
        """Non-owner (non-admin) cannot revoke someone else's share → 403."""
        # Admin creates a share to bob.
        r = await shares_client.post(
            "/api/shares",
            json={
                "resource_type": "project",
                "resource_id": "proj-revoke-403",
                "to_username": "bob",
                "permission": "read",
            },
        )
        assert r.status_code == 200
        share_id = r.json()["id"]

        # Bob tries to revoke it — bob is target, not owner, and not admin.
        resp = await bob_client.delete(f"/api/shares/{share_id}")
        assert resp.status_code == 403
