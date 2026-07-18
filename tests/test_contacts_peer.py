"""Tests for contacts_store, peer envelope crypto, and peer routes."""
from __future__ import annotations

import json
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tinyagentos.contacts_store import ContactsStore, generate_peer_token, _hash_token
from tinyagentos.peer import (
    build_envelope,
    verify_envelope,
    verify_envelope_signature,
    mint_peer_token,
)


# ---------------------------------------------------------------------------
# contacts_store tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def store(tmp_path):
    s = ContactsStore(tmp_path / "contacts.db")
    await s.init()
    yield s
    await s.close()


@pytest.mark.asyncio
class TestContactsStore:
    async def test_add_and_get_contact(self, store):
        await store.add_contact(
            contact_id="hub:hogne",
            hub_username="hogne",
            display_name="Hogne",
            ed25519_pub="abc123",
            x25519_pub="def456",
        )
        c = await store.get_contact("hub:hogne")
        assert c is not None
        assert c["contact_id"] == "hub:hogne"
        assert c["hub_username"] == "hogne"
        assert c["display_name"] == "Hogne"
        assert c["ed25519_pub"] == "abc123"
        assert c["x25519_pub"] == "def456"
        assert c["status"] == "active"

    async def test_get_contact_not_found(self, store):
        assert await store.get_contact("hub:nonexistent") is None

    async def test_get_contact_by_username(self, store):
        await store.add_contact(
            contact_id="hub:hogne",
            hub_username="hogne",
            display_name="H",
            ed25519_pub="pk",
            x25519_pub="ek",
        )
        c = await store.get_contact_by_username("hogne")
        assert c is not None
        assert c["contact_id"] == "hub:hogne"

    async def test_upsert_contact(self, store):
        await store.add_contact(
            contact_id="hub:hogne",
            hub_username="hogne",
            display_name="Hogne v1",
            ed25519_pub="old-key",
            x25519_pub="old-enc",
        )
        # Re-add with new key material
        await store.add_contact(
            contact_id="hub:hogne",
            hub_username="hogne",
            display_name="Hogne v2",
            ed25519_pub="new-key",
            x25519_pub="new-enc",
        )
        c = await store.get_contact("hub:hogne")
        assert c["ed25519_pub"] == "new-key"
        assert c["x25519_pub"] == "new-enc"
        assert c["display_name"] == "Hogne v2"

    async def test_list_contacts(self, store):
        await store.add_contact(
            contact_id="hub:a", hub_username="a", display_name="A",
            ed25519_pub="pk", x25519_pub="ek",
        )
        await store.add_contact(
            contact_id="hub:b", hub_username="b", display_name="B",
            ed25519_pub="pk", x25519_pub="ek",
        )
        contacts = await store.list_contacts()
        assert len(contacts) == 2

    async def test_list_contacts_filtered(self, store):
        await store.add_contact(
            contact_id="hub:a", hub_username="a", display_name="A",
            ed25519_pub="pk", x25519_pub="ek", status="active",
        )
        await store.add_contact(
            contact_id="hub:b", hub_username="b", display_name="B",
            ed25519_pub="pk", x25519_pub="ek", status="blocked",
        )
        active = await store.list_contacts(status="active")
        assert len(active) == 1
        assert active[0]["contact_id"] == "hub:a"

    async def test_set_contact_status(self, store):
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        await store.set_contact_status("hub:hogne", "blocked")
        c = await store.get_contact("hub:hogne")
        assert c["status"] == "blocked"
        assert c["revoked_at"] is not None

    async def test_peer_link_establish_and_lookup(self, store):
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        outbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:hogne",
            inbound_token=inbound,
            outbound_token=outbound,
            endpoints=["https://hogne.example.com:6969"],
        )
        link = await store.get_peer_link("hub:hogne")
        assert link is not None
        assert link["inbound_token_hash"] == _hash_token(inbound)
        assert link["outbound_token"] == outbound
        assert link["endpoints"] == ["https://hogne.example.com:6969"]

    async def test_find_contact_by_inbound_token(self, store):
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:hogne",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )
        contact = await store.find_contact_by_inbound_token(inbound)
        assert contact is not None
        assert contact["contact_id"] == "hub:hogne"

    async def test_find_contact_by_invalid_token(self, store):
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:hogne",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )
        assert await store.find_contact_by_inbound_token("bogus-token") is None

    async def test_find_contact_token_revoked_contact(self, store):
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:hogne",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )
        await store.set_contact_status("hub:hogne", "revoked")
        assert await store.find_contact_by_inbound_token(inbound) is None

    async def test_mark_peer_seen(self, store):
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        await store.establish_peer_link(
            contact_id="hub:hogne",
            inbound_token=generate_peer_token(),
            outbound_token=generate_peer_token(),
        )
        await store.mark_peer_seen("hub:hogne")
        link = await store.get_peer_link("hub:hogne")
        assert link["last_seen_at"] is not None

    async def test_revoke_peer_link_cascades(self, store):
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        await store.establish_peer_link(
            contact_id="hub:hogne",
            inbound_token=generate_peer_token(),
            outbound_token=generate_peer_token(),
        )
        await store.revoke_peer_link("hub:hogne")
        link = await store.get_peer_link("hub:hogne")
        assert link["revoked_at"] is not None
        c = await store.get_contact("hub:hogne")
        assert c["status"] == "revoked"


# ---------------------------------------------------------------------------
# peer envelope crypto tests
# ---------------------------------------------------------------------------


class TestPeerEnvelope:
    def test_build_envelope_structure(self):
        env = build_envelope(
            from_username="jaylfc",
            to_username="hogne",
            kind="handshake",
            body={"greeting": "hello"},
        )
        assert env["from"] == "hub:jaylfc"
        assert env["to"] == "hub:hogne"
        assert env["kind"] == "handshake"
        assert env["body"] == {"greeting": "hello"}
        assert "ts" in env
        assert "nonce" in env
        assert "sig" in env
        assert len(env["sig"]) == 128  # 64 bytes hex

    def test_build_envelope_no_body(self):
        env = build_envelope(
            from_username="jaylfc",
            to_username="hogne",
            kind="ack",
        )
        assert "body" not in env
        assert env["kind"] == "ack"

    def test_verify_envelope_fresh(self):
        env = build_envelope(
            from_username="jaylfc",
            to_username="hogne",
            kind="handshake",
        )
        ok, err = verify_envelope(env)
        assert err == "", f"expected empty error, got: {err}"

    def test_verify_envelope_missing_field(self):
        env = {"from": "hub:jaylfc", "kind": "handshake"}
        ok, err = verify_envelope(env)
        assert not ok
        assert "missing required field" in err

    def test_verify_envelope_wrong_kind(self):
        env = build_envelope(
            from_username="jaylfc",
            to_username="hogne",
            kind="handshake",
        )
        ok, err = verify_envelope(env, expected_kind="chat")
        assert not ok
        assert "unexpected kind" in err

    def test_verify_envelope_too_old(self):
        env = build_envelope(
            from_username="jaylfc",
            to_username="hogne",
            kind="handshake",
        )
        # Artificially age the timestamp
        env["ts"] = time.time() - 400  # 400 seconds ago
        ok, err = verify_envelope(env, max_age_seconds=300)
        assert not ok
        assert "too old" in err

    def test_verify_envelope_signature_roundtrip(self):
        """Verify that a locally-built envelope's signature passes verification."""
        from tinyagentos.hub.identity import load_or_create, clear as _clear, public_identity

        # Generate a fresh identity for this test
        _clear()
        identity = load_or_create()
        pub = public_identity()
        signing_pub = pub["signing_pubkey"]

        env = build_envelope(
            from_username="jaylfc",
            to_username="hogne",
            kind="handshake",
            body={"hello": "world"},
        )

        # Remove sig to re-verify
        assert verify_envelope_signature(env, signing_pub), "own signature must verify"

        # Clean up
        _clear()

    def test_verify_envelope_bad_signature(self):
        """Tempered envelope fails signature verification."""
        from tinyagentos.hub.identity import load_or_create, clear as _clear, public_identity

        _clear()
        identity = load_or_create()
        pub = public_identity()
        signing_pub = pub["signing_pubkey"]

        env = build_envelope(
            from_username="jaylfc",
            to_username="hogne",
            kind="handshake",
        )
        # Tamper with the payload
        env["kind"] = "evil"
        assert not verify_envelope_signature(env, signing_pub)

        _clear()

    def test_verify_envelope_signature_restores_dict(self):
        """verify_envelope_signature restores the 'sig' field after popping it."""
        from tinyagentos.hub.identity import load_or_create, clear as _clear, public_identity

        _clear()
        identity = load_or_create()
        pub = public_identity()
        signing_pub = pub["signing_pubkey"]

        env = build_envelope(
            from_username="jaylfc",
            to_username="hogne",
            kind="handshake",
        )
        original_sig = env["sig"]
        verify_envelope_signature(env, signing_pub)
        assert env["sig"] == original_sig  # restored

        _clear()


# ---------------------------------------------------------------------------
# peer token tests
# ---------------------------------------------------------------------------


class TestPeerTokens:
    def test_mint_peer_token(self):
        token, token_hash = mint_peer_token("contact:hogne")
        assert len(token) == 64  # 32 bytes hex
        assert len(token_hash) == 64  # SHA-256 hex
        # mint_peer_token and _hash_token now use the same plain SHA-256.
        assert token_hash == _hash_token(token)

    def test_token_hash_deterministic(self):
        token = generate_peer_token()
        assert _hash_token(token) == _hash_token(token)

    def test_token_hash_different_tokens(self):
        t1 = generate_peer_token()
        t2 = generate_peer_token()
        assert _hash_token(t1) != _hash_token(t2)

    def test_mint_peer_token_unique(self):
        t1, _ = mint_peer_token("contact:a")
        t2, _ = mint_peer_token("contact:b")
        assert t1 != t2


# ---------------------------------------------------------------------------
# peer route integration tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_with_contacts(tmp_data_dir):
    """Create an app and initialise the contacts store."""
    from tinyagentos.app import create_app

    _app = create_app(data_dir=tmp_data_dir)

    # Initialise contacts_store (not done by create_app for peers)
    store = _app.state.contacts_store
    if store._db is not None:
        await store.close()
    await store.init()

    return _app


@pytest_asyncio.fixture
async def client_with_contacts(app_with_contacts):
    """Async client with contacts_store initialized and auth bypassed for peer routes."""
    _app = app_with_contacts

    # Set up auth user for admin session
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


@pytest.mark.asyncio
class TestPeerRoutes:
    async def test_inbox_missing_token(self, client_with_contacts):
        resp = await client_with_contacts.post(
            "/api/peer/inbox",
            json={"envelope": {}},
        )
        assert resp.status_code == 401

    async def test_inbox_invalid_token(self, client_with_contacts):
        resp = await client_with_contacts.post(
            "/api/peer/inbox",
            json={"envelope": {}},
            headers={"Authorization": "Bearer bogus"},
        )
        assert resp.status_code == 401

    async def test_inbox_rate_limit(self, client_with_contacts, app_with_contacts):
        """Verify rate limiting kicks in after 60 requests in a window."""
        store = app_with_contacts.state.contacts_store
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:hogne",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )

        headers = {"Authorization": f"Bearer {inbound}"}

        # The route returns 400 for invalid envelopes but 429 if rate-limited.
        # Send 61 requests — the 61st should be 429.
        statuses = []
        for _ in range(65):
            resp = await client_with_contacts.post(
                "/api/peer/inbox",
                json={"envelope": {}},
                headers=headers,
            )
            statuses.append(resp.status_code)

        assert 429 in statuses, f"expected 429 in statuses, got: {set(statuses)}"

    async def test_inbox_envelope_too_large(self, client_with_contacts, app_with_contacts):
        store = app_with_contacts.state.contacts_store
        await store.add_contact(
            contact_id="hub:big-msg", hub_username="big-msg", display_name="B",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:big-msg",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )

        # Create an envelope that's too large
        big_body = "x" * (33 * 1024)  # 33 KB > 32 KB limit
        resp = await client_with_contacts.post(
            "/api/peer/inbox",
            json={"envelope": {"body": big_body}},
            headers={"Authorization": f"Bearer {inbound}"},
        )
        assert resp.status_code == 413

    async def test_inbox_wrong_to_field(self, client_with_contacts, app_with_contacts):
        """Envelope addressed to a different contact must be rejected."""
        from tinyagentos.peer import build_envelope

        store = app_with_contacts.state.contacts_store
        await store.add_contact(
            contact_id="hub:wrong-to", hub_username="wrong-to", display_name="W",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:wrong-to",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )

        env = build_envelope(
            from_username="jaylfc",
            to_username="someone-else",  # wrong recipient
            kind="handshake",
        )
        resp = await client_with_contacts.post(
            "/api/peer/inbox",
            json={"envelope": env},
            headers={"Authorization": f"Bearer {inbound}"},
        )
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"

    async def test_inbox_nonce_replay(self, client_with_contacts, app_with_contacts):
        """Replaying an envelope with the same nonce must return 409."""
        from tinyagentos.peer import build_envelope

        store = app_with_contacts.state.contacts_store
        await store.add_contact(
            contact_id="hub:nonce-test", hub_username="nonce-test", display_name="N",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:nonce-test",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )

        env = build_envelope(
            from_username="jaylfc",
            to_username="nonce-test",
            kind="handshake",
        )

        headers = {"Authorization": f"Bearer {inbound}"}

        # First delivery — should succeed (200 or 400 depending on sig check;
        # the key point is it's not 409).
        resp1 = await client_with_contacts.post(
            "/api/peer/inbox",
            json={"envelope": env},
            headers=headers,
        )
        assert resp1.status_code != 409, f"first send should not be replay: {resp1.status_code}"

        # Replay the same envelope — must be 409 Conflict.
        resp2 = await client_with_contacts.post(
            "/api/peer/inbox",
            json={"envelope": env},
            headers=headers,
        )
        assert resp2.status_code == 409, f"replay should be 409, got {resp2.status_code}: {resp2.text}"

    async def test_peer_routes_csrf_exempt(self, client_with_contacts, app_with_contacts):
        """Peer routes should work without a CSRF token (bearer-only auth)."""
        store = app_with_contacts.state.contacts_store
        await store.add_contact(
            contact_id="hub:hogne", hub_username="hogne", display_name="H",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:hogne",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )

        # POST without CSRF header — should NOT get 403 CSRF error
        resp = await client_with_contacts.post(
            "/api/peer/ack",
            json={"envelope_id": "test-nonce", "contact_id": "hub:hogne"},
            headers={"Authorization": f"Bearer {inbound}"},
        )
        # Won't be 403 CSRF — auth passes even without CSRF header
        assert resp.status_code != 403

    async def test_ack_endpoint(self, client_with_contacts, app_with_contacts):
        store = app_with_contacts.state.contacts_store
        await store.add_contact(
            contact_id="hub:ack-test", hub_username="ack-test", display_name="A",
            ed25519_pub="pk", x25519_pub="ek",
        )
        inbound = generate_peer_token()
        await store.establish_peer_link(
            contact_id="hub:ack-test",
            inbound_token=inbound,
            outbound_token=generate_peer_token(),
        )

        resp = await client_with_contacts.post(
            "/api/peer/ack",
            json={"envelope_id": "test-nonce-123", "contact_id": "hub:ack-test"},
            headers={"Authorization": f"Bearer {inbound}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "acked"
        assert data["envelope_id"] == "test-nonce-123"
