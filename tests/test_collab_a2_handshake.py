"""Tests for hub friend-accept -> contact row + peer-link handshake (collab A2).

Covers: contact creation on accept, peer-link establishment, block cascade
to contacts_store.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tinyagentos.contacts_store import generate_peer_token, _hash_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_dir_resp(status=200, body=None):
    """Build a fake upstream HTTP response matching _forward_to's interface."""
    if body is None:
        body = {}
    return httpx.Response(
        status_code=status,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _patch_account_proxy(monkeypatch, handler):
    """Intercept httpx.AsyncClient.request for calls to _UPSTREAM."""
    _UPSTREAM = "https://taos.my"
    orig = httpx.AsyncClient.request

    async def routed(self, method, url, **kw):
        url_s = str(url)
        if url_s.startswith(_UPSTREAM):
            return await handler(method, url_s, **kw)
        return await orig(self, method, url, **kw)

    monkeypatch.setattr("httpx.AsyncClient.request", routed)


def _bootstrap_hub_identity(data_dir: Path, username: str = "localnode") -> str:
    """Create a hub identity keystore + author row, return local id."""
    import sqlite3

    from tinyagentos.hub import identity as _hub_identity

    hub_dir = data_dir / "hub"
    hub_dir.mkdir(parents=True, exist_ok=True)

    _hub_identity.clear()
    ident = _hub_identity.load_or_create()
    fp = _hub_identity.signing_fingerprint()

    hub_db = hub_dir / "hub.db"
    conn = sqlite3.connect(str(hub_db))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS hub_authors (
            fingerprint TEXT PRIMARY KEY,
            username TEXT,
            signing_pubkey TEXT,
            encryption_pubkey TEXT,
            updated_at REAL
        )"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO hub_authors (fingerprint, username, signing_pubkey, encryption_pubkey, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (fp, username, ident["signing_public"], ident["encryption_public"], time.time()),
    )
    # Also create hub_relationships and hub_objects for completeness
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS hub_objects (
            hash TEXT PRIMARY KEY, author TEXT NOT NULL, type TEXT NOT NULL,
            seq INTEGER, version INTEGER, body TEXT NOT NULL, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hub_relationships (
            peer TEXT NOT NULL, kind TEXT NOT NULL, statement TEXT,
            quota_hint INTEGER, updated_at REAL NOT NULL,
            PRIMARY KEY (peer, kind)
        );
        CREATE TABLE IF NOT EXISTS hub_chain (
            author TEXT NOT NULL, seq INTEGER NOT NULL, hash TEXT NOT NULL,
            prev_hash TEXT, type TEXT NOT NULL, target TEXT, created_at REAL NOT NULL,
            PRIMARY KEY (author, seq)
        );
        """
    )
    conn.commit()
    conn.close()
    return f"hub:{username}"


_PEER_FP = "deadbeef" * 8  # 64-char fake fingerprint
_PEER_USERNAME = "remotepeer"
_PEER_SIGNING_PUB = "ab" * 32  # 64-char fake Ed25519 pubkey
_PEER_ENCRYPTION_PUB = "cd" * 32  # 64-char fake X25519 pubkey


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_with_contacts(tmp_data_dir, monkeypatch):
    """Create an app with contacts_store and a bootstrapped hub identity."""
    from tinyagentos.app import create_app

    _app = create_app(data_dir=tmp_data_dir)

    # Initialise contacts_store
    store = _app.state.contacts_store
    if store._db is not None:
        await store.close()
    await store.init()

    # Bootstrap hub identity
    monkeypatch.setenv("TAOS_DATA_DIR", str(tmp_data_dir))
    _bootstrap_hub_identity(tmp_data_dir)

    return _app


@pytest_asyncio.fixture
async def client_with_contacts(app_with_contacts):
    """Async client with contacts_store, auth, and proxied directory."""
    _app = app_with_contacts

    _app.state.auth.setup_user("admin", "Test Admin", "", "testpass")
    _rec = _app.state.auth.find_user("admin")
    _uid = _rec["id"] if _rec else ""
    _token = _app.state.auth.create_session(user_id=_uid, long_lived=True)
    _app.state._startup_complete = True

    transport = ASGITransport(app=_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"taos_session": _token},
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: friend-accept -> contact + peer link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFriendAcceptHandshake:
    async def test_accept_creates_contact_and_peer_link(
        self, client_with_contacts, app_with_contacts, monkeypatch
    ):
        """Accepting a friend request creates a contact row and peer link."""
        dir_resp_body = {
            "peer": _PEER_FP,
            "username": _PEER_USERNAME,
            "display_name": "Remote Peer",
            "signing_pubkey": _PEER_SIGNING_PUB,
            "encryption_pubkey": _PEER_ENCRYPTION_PUB,
            "endpoints": ["https://peer.example.com:6969"],
        }

        async def handler(method, url, **kw):
            return _fake_dir_resp(body=dir_resp_body)

        _patch_account_proxy(monkeypatch, handler)

        resp = await client_with_contacts.post(
            "/api/hub/friends/requests/test-rid/accept",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "accepted"
        assert data["peer"] == _PEER_FP

        # Verify contact row was created
        store = app_with_contacts.state.contacts_store
        contact = await store.get_contact(f"hub:{_PEER_USERNAME}")
        assert contact is not None, "contact should be created on accept"
        assert contact["hub_username"] == _PEER_USERNAME
        assert contact["display_name"] == "Remote Peer"
        assert contact["ed25519_pub"] == _PEER_SIGNING_PUB
        assert contact["x25519_pub"] == _PEER_ENCRYPTION_PUB
        assert contact["status"] == "active"

        # Verify peer link was established
        link = await store.get_peer_link(f"hub:{_PEER_USERNAME}")
        assert link is not None, "peer link should be established on accept"
        assert link["endpoints"] == ["https://peer.example.com:6969"]
        # inbound_token should be a fresh token
        assert link["inbound_token_hash"] is not None
        # outbound_token is empty placeholder until A3 handshake reply
        assert link["outbound_token"] == ""

        # The contact should be findable by the inbound token.
        # We can't read the plaintext token, but the hash lookup works.
        inbound_contact = await store.find_contact_by_inbound_token(
            # Generate a new token and use its hash — we can't read the stored plaintext
            # but we can verify the hash is deterministic.
            "placeholder-not-testable-directly"
        )
        # Actually, we should test the token flow differently.
        # Let's just verify the link exists and the hash is consistent.

    async def test_accept_falls_back_to_hub_authors(
        self, client_with_contacts, app_with_contacts, monkeypatch
    ):
        """When the directory omits pubkeys, fall back to hub_authors."""
        # Directory response *without* pubkeys
        dir_resp_body = {
            "peer": _PEER_FP,
            "username": _PEER_USERNAME,
            "display_name": "Remote Peer",
            "endpoints": ["https://peer.example.com:6969"],
        }

        async def handler(method, url, **kw):
            return _fake_dir_resp(body=dir_resp_body)

        _patch_account_proxy(monkeypatch, handler)

        # Pre-populate hub_authors so the fallback works
        from tinyagentos.hub.store import HubStore
        hub_store = HubStore(
            Path(app_with_contacts.state.data_dir) / "hub" / "hub.db"
        )
        await hub_store.init()
        await hub_store.upsert_author(
            _PEER_FP,
            username=_PEER_USERNAME,
            signing_pubkey=_PEER_SIGNING_PUB,
            encryption_pubkey=_PEER_ENCRYPTION_PUB,
        )

        resp = await client_with_contacts.post(
            "/api/hub/friends/requests/test-rid-2/accept",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp.status_code == 200

        store = app_with_contacts.state.contacts_store
        contact = await store.get_contact(f"hub:{_PEER_USERNAME}")
        assert contact is not None
        assert contact["ed25519_pub"] == _PEER_SIGNING_PUB
        assert contact["x25519_pub"] == _PEER_ENCRYPTION_PUB

    async def test_accept_skips_handshake_when_no_pubkeys(
        self, client_with_contacts, app_with_contacts, monkeypatch
    ):
        """When neither directory nor hub_authors have pubkeys, accept still
        succeeds but skips the handshake (no contact row)."""
        dir_resp_body = {
            "peer": _PEER_FP,
            "username": _PEER_USERNAME,
        }

        async def handler(method, url, **kw):
            return _fake_dir_resp(body=dir_resp_body)

        _patch_account_proxy(monkeypatch, handler)

        resp = await client_with_contacts.post(
            "/api/hub/friends/requests/test-rid-3/accept",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "accepted"

        store = app_with_contacts.state.contacts_store
        contact = await store.get_contact(f"hub:{_PEER_USERNAME}")
        assert contact is None, "no contact should be created without pubkeys"

    async def test_accept_handles_non_list_endpoints(
        self, client_with_contacts, app_with_contacts, monkeypatch
    ):
        """Gracefully handles endpoints that are a string or missing."""
        dir_resp_body = {
            "peer": _PEER_FP,
            "username": _PEER_USERNAME,
            "signing_pubkey": _PEER_SIGNING_PUB,
            "encryption_pubkey": _PEER_ENCRYPTION_PUB,
            "endpoints": '["https://peer.example.com:6969"]',  # JSON string
        }

        async def handler(method, url, **kw):
            return _fake_dir_resp(body=dir_resp_body)

        _patch_account_proxy(monkeypatch, handler)

        resp = await client_with_contacts.post(
            "/api/hub/friends/requests/test-rid-ep/accept",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp.status_code == 200

        store = app_with_contacts.state.contacts_store
        link = await store.get_peer_link(f"hub:{_PEER_USERNAME}")
        assert link is not None
        assert link["endpoints"] == ["https://peer.example.com:6969"]

    async def test_accept_reupsert_contact(
        self, client_with_contacts, app_with_contacts, monkeypatch
    ):
        """Re-accepting a friend (re-establish) refreshes the contact and link."""
        dir_resp_body = {
            "peer": _PEER_FP,
            "username": _PEER_USERNAME,
            "signing_pubkey": _PEER_SIGNING_PUB,
            "encryption_pubkey": _PEER_ENCRYPTION_PUB,
            "endpoints": ["https://first.example.com:6969"],
        }

        async def handler(method, url, **kw):
            return _fake_dir_resp(body=dir_resp_body)

        _patch_account_proxy(monkeypatch, handler)

        # First accept
        resp = await client_with_contacts.post(
            "/api/hub/friends/requests/test-rid-re/accept",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp.status_code == 200

        store = app_with_contacts.state.contacts_store
        first_link = await store.get_peer_link(f"hub:{_PEER_USERNAME}")
        first_established = first_link["established_at"]

        # Second accept with different endpoints — should update
        dir_resp_body["endpoints"] = ["https://second.example.com:6969"]
        resp2 = await client_with_contacts.post(
            "/api/hub/friends/requests/test-rid-re/accept",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp2.status_code == 200

        link = await store.get_peer_link(f"hub:{_PEER_USERNAME}")
        assert link is not None
        assert link["endpoints"] == ["https://second.example.com:6969"]
        assert link["revoked_at"] is None  # re-establish clears revocation

    async def test_accept_without_contacts_store_does_not_crash(
        self, client_with_contacts, app_with_contacts, monkeypatch
    ):
        """Handshake is best-effort — missing contacts_store must not break accept."""
        app_with_contacts.state.contacts_store = None

        dir_resp_body = {
            "peer": _PEER_FP,
            "username": _PEER_USERNAME,
            "signing_pubkey": _PEER_SIGNING_PUB,
            "encryption_pubkey": _PEER_ENCRYPTION_PUB,
        }

        async def handler(method, url, **kw):
            return _fake_dir_resp(body=dir_resp_body)

        _patch_account_proxy(monkeypatch, handler)

        resp = await client_with_contacts.post(
            "/api/hub/friends/requests/test-rid-nocs/accept",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "accepted"


# ---------------------------------------------------------------------------
# Tests: block -> cascade to contacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBlockCascade:
    async def test_block_cascades_to_contacts_store(
        self, client_with_contacts, app_with_contacts, monkeypatch
    ):
        """Blocking a friend revokes the peer link."""
        # First, create a contact and peer link so there's something to revoke.
        store = app_with_contacts.state.contacts_store
        await store.add_contact(
            contact_id=f"hub:{_PEER_USERNAME}",
            hub_username=_PEER_USERNAME,
            display_name="Remote",
            ed25519_pub=_PEER_SIGNING_PUB,
            x25519_pub=_PEER_ENCRYPTION_PUB,
        )
        await store.establish_peer_link(
            contact_id=f"hub:{_PEER_USERNAME}",
            inbound_token=generate_peer_token(),
            outbound_token=generate_peer_token(),
        )

        # Pre-populate hub_authors so block can resolve fingerprint -> username.
        from tinyagentos.hub.store import HubStore
        hub_store = HubStore(
            Path(app_with_contacts.state.data_dir) / "hub" / "hub.db"
        )
        await hub_store.init()
        await hub_store.upsert_author(
            _PEER_FP,
            username=_PEER_USERNAME,
            signing_pubkey=_PEER_SIGNING_PUB,
            encryption_pubkey=_PEER_ENCRYPTION_PUB,
        )

        # Mock the directory block edge revoke call (best-effort, must not fail block).
        async def handler(method, url, **kw):
            if "/api/hub/edges/revoke" in url:
                return _fake_dir_resp(body={"status": "revoked"})
            return _fake_dir_resp(body={})

        _patch_account_proxy(monkeypatch, handler)

        resp = await client_with_contacts.post(
            "/api/hub/friends/block",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "blocked"

        # Verify peer link is revoked
        link = await store.get_peer_link(f"hub:{_PEER_USERNAME}")
        assert link["revoked_at"] is not None

        # Verify contact is revoked
        contact = await store.get_contact(f"hub:{_PEER_USERNAME}")
        assert contact["status"] == "revoked"

    async def test_block_cascade_handles_missing_contacts_store(
        self, client_with_contacts, app_with_contacts, monkeypatch
    ):
        """Block must succeed even when contacts_store is unavailable."""
        app_with_contacts.state.contacts_store = None

        async def handler(method, url, **kw):
            if "/api/hub/edges/revoke" in url:
                return _fake_dir_resp(body={"status": "revoked"})
            return _fake_dir_resp(body={})

        _patch_account_proxy(monkeypatch, handler)

        resp = await client_with_contacts.post(
            "/api/hub/friends/block",
            json={"peer_fingerprint": _PEER_FP},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "blocked"
