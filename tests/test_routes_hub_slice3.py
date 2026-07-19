"""Local hub social routes (hub social slice 3).

Exercises the Friends surface: signed follow / cache-grant statements are stored
(the cache grant is noted as not-yet-acted-on), the friend-request send/accept/
decline flows broker through the directory, and the local block / mute operations
work. The directory (taos.my) is a contract here, so its upstream calls are
mocked; the meaningful edge-authorization check (presence denied without an
accepted edge) and the block-severs-edge behavior are asserted locally.
"""
from __future__ import annotations

import json

import httpx
import pytest

from tinyagentos.hub import identity, relationships
from tinyagentos.hub import store as hub_store


_UPSTREAM = "https://taos.my"


class _FakeResp:
    def __init__(self, content=b"{}", status=200, headers=None):
        self.content = content
        self.status_code = status
        self.headers = httpx.Headers(headers or {})


@pytest.fixture(autouse=True)
def _isolate_hub_data(tmp_data_dir, monkeypatch):
    # Both the identity keystore and the hub store resolve from TAOS_DATA_DIR, so
    # pointing it at the per-test data dir keeps every request hermetic.
    monkeypatch.setenv("TAOS_DATA_DIR", str(tmp_data_dir))
    monkeypatch.setenv("TAOS_ACCOUNT_BASE_URL", "https://taos.my/")
    return tmp_data_dir


@pytest.fixture
def upstream(monkeypatch):
    """A configurable mock of the taos.my directory. Returns 200 '{}' by default;
    tests override ``handler`` to assert the forwarded call or to return 403/429."""
    captured: list[dict] = []
    calls = {"handler": None}

    async def _default(method, url, **kw):
        return _FakeResp()

    calls["handler"] = _default

    _real = httpx.AsyncClient.request

    async def _routed(self, method, url, **kw):
        if str(url).startswith(_UPSTREAM):
            # Always record the forwarded directory call, regardless of the test's
            # handler, so assertions about "was it forwarded?" hold for any handler.
            captured.append({"method": method, "url": str(url),
                            "body": (kw.get("content") or b"").decode("utf-8", "replace")})
            return await calls["handler"](method, str(url), **kw)
        # Relative ASGI call (the test client transport) passes through to real httpx.
        return await _real(self, method, url, **kw)

    monkeypatch.setattr("httpx.AsyncClient.request", _routed)
    return captured, calls


def _set(upstream, fn):
    upstream[1]["handler"] = fn


class TestFollowAndCacheGrant:
    @pytest.mark.asyncio
    async def test_follow_publishes_signed_statement(self, client):
        resp = await client.put(
            "/api/hub/follow", json={"target_fingerprint": "peerFP"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "following"
        # The stored statement verifies against this node's own signing key.
        pub = identity.public_identity()["signing_pubkey"]
        assert identity.verify_signature(
            pub,
            hub_store.canonical_bytes(body["statement"]),
            body["statement"]["sig"],
        )

    @pytest.mark.asyncio
    async def test_cache_grant_is_stored_not_yet_acted_on(self, client):
        resp = await client.put(
            "/api/hub/cache-grant",
            json={"grantee_fingerprint": "granteeFP", "quota_hint": 1234},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "granted"
        assert body["quota_hint"] == 1234
        # The composer/UI must label it as stored-but-inert until slice 6 lands.
        assert "not yet acted on" in body["note"]

    @pytest.mark.asyncio
    async def test_cache_grant_defaults_quota(self, client):
        resp = await client.put(
            "/api/hub/cache-grant", json={"grantee_fingerprint": "g"}
        )
        assert resp.status_code == 200
        assert resp.json()["quota_hint"] == relationships.DEFAULT_CACHE_QUOTA_BYTES


class TestFriendsList:
    @pytest.mark.asyncio
    async def test_list_groups_local_relationships(self, client):
        await client.put("/api/hub/follow", json={"target_fingerprint": "p1"})
        await client.put(
            "/api/hub/cache-grant", json={"grantee_fingerprint": "p2", "quota_hint": 5}
        )
        await client.post("/api/hub/friends/block", json={"peer_fingerprint": "p3"})
        resp = await client.get("/api/hub/friends")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "ok"
        assert body["follows_out"] == ["p1"]
        assert [g["peer"] for g in body["cache_grants"]] == ["p2"]
        assert body["blocks"] == ["p3"]


class TestBlockMute:
    @pytest.mark.asyncio
    async def test_block_severs_local_edges(self, client, upstream):
        # Establish a friend edge + a follow, then block.
        captured, calls = upstream
        await client.put("/api/hub/follow", json={"target_fingerprint": "peerFP"})

        async def accept_handler(method, url, **kw):
            return _FakeResp(content=json.dumps({"peer": "peerFP", "endpoints": ["wss://x"]}).encode())
        _set(upstream, accept_handler)
        resp = await client.post("/api/hub/friends/requests/rid-1/accept",
                                 json={"peer_fingerprint": "peerFP"})
        assert resp.json()["state"] == "accepted"

        # Before block, presence is authorized (forwarded to the directory).
        async def pres_handler(method, url, **kw):
            return _FakeResp(content=json.dumps({"endpoints": ["wss://x"]}).encode())
        _set(upstream, pres_handler)
        resp = await client.get("/api/hub/presence?peer=peerFP&username=alice")
        assert resp.status_code == 200

        # Block: severs the friend + follow edges locally and asks the hub to
        # revoke the server-side edge.
        resp = await client.post("/api/hub/friends/block", json={"peer_fingerprint": "peerFP"})
        assert resp.json()["state"] == "blocked"
        assert relationships.REL_FRIEND in resp.json()["severed"]
        # The directory revoke call was made.
        revoke = [c for c in captured if c["url"].endswith("/api/hub/edges/revoke")]
        assert revoke, "directory edge revoke not called"

        # After block, presence is denied (no accepted edge) even though the
        # directory would also deny it: the local gate is the authority that matters.
        _set(upstream, pres_handler)
        resp = await client.get("/api/hub/presence?peer=peerFP&username=alice")
        assert resp.status_code == 403
        assert resp.json()["reason"] == "no accepted edge"
        # And the friend list no longer shows the peer.
        friends = (await client.get("/api/hub/friends")).json()
        assert friends["friends"] == []
        assert friends["blocks"] == ["peerFP"]

    @pytest.mark.asyncio
    async def test_mute_and_unmute_are_local(self, client, upstream):
        resp = await client.post("/api/hub/friends/mute", json={"peer_fingerprint": "p1"})
        assert resp.json()["state"] == "muted"
        assert (await client.get("/api/hub/friends")).json()["mutes"] == ["p1"]
        resp = await client.post("/api/hub/friends/unmute", json={"peer_fingerprint": "p1"})
        assert resp.json()["state"] == "unmuted"
        assert (await client.get("/api/hub/friends")).json()["mutes"] == []


class TestFriendRequestFlow:
    @pytest.mark.asyncio
    async def test_send_brokers_signed_intro_and_stores_out(self, client, upstream):
        captured, calls = upstream
        async def handler(method, url, **kw):
            return _FakeResp(content=json.dumps({"request_id": "r1"}).encode())
        _set(upstream, handler)
        resp = await client.post(
            "/api/hub/friends/request",
            json={"target_fingerprint": "peerFP", "intro": "hi"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "sent"
        # The forwarded body is a signed intro (to/author/intro/sig), not raw JSON.
        sent = [c for c in captured if c["url"].endswith("/api/hub/requests")][0]
        intro = json.loads(sent["body"])
        assert intro["to"] == "peerFP"
        assert intro["intro"] == "hi"
        assert "sig" in intro and "author" in intro

    @pytest.mark.asyncio
    async def test_accept_records_friend_edge(self, client, upstream):
        captured, calls = upstream
        await client.put("/api/hub/follow", json={"target_fingerprint": "peerFP"})

        async def handler(method, url, **kw):
            return _FakeResp(content=json.dumps({"peer": "peerFP", "endpoints": []}).encode())
        _set(upstream, handler)
        resp = await client.post(
            "/api/hub/friends/requests/rid-9/accept",
            json={"peer_fingerprint": "peerFP"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "accepted"
        friends = (await client.get("/api/hub/friends")).json()["friends"]
        assert friends == ["peerFP"]

    @pytest.mark.asyncio
    async def test_decline_records_declined(self, client, upstream):
        captured, calls = upstream

        async def handler(method, url, **kw):
            return _FakeResp(content=json.dumps({"peer": "peerFP"}).encode())
        _set(upstream, handler)
        resp = await client.post(
            "/api/hub/friends/requests/rid-9/decline"
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "declined"
        decl = (await client.get("/api/hub/friends")).json()["requests_declined"]
        assert decl == ["peerFP"]


class TestPresenceGate:
    @pytest.mark.asyncio
    async def test_presence_denied_without_accepted_edge(self, client, upstream):
        # Establish an identity (no friend edge for peerFP): the gate returns 403
        # before any upstream call.
        await client.put("/api/hub/follow", json={"target_fingerprint": "peerFP"})
        captured, calls = upstream
        resp = await client.get("/api/hub/presence?peer=peerFP&username=alice")
        assert resp.status_code == 403
        assert resp.json()["error"] == "not authorized"
        # The directory was never consulted.
        assert [c for c in captured if "presence" in c["url"]] == []

    @pytest.mark.asyncio
    async def test_presence_requires_identity(self, client, upstream):
        # Without an identity the degrade state is reported (not a 403 auth error).
        # Minting does not happen on a pure presence read, so identity is absent.
        # Force the no-identity path by clearing the keystore first.
        from tinyagentos.hub import identity as idmod
        idmod.clear()
        resp = await client.get("/api/hub/presence?peer=peerFP&username=alice")
        assert resp.status_code == 200
        assert resp.json() == {"state": "no-identity"}

    @pytest.mark.asyncio
    async def test_presence_forwarded_when_edge_exists(self, client, upstream):
        captured, calls = upstream
        # Establish the accepted edge via accept.
        async def accept_handler(method, url, **kw):
            return _FakeResp(content=json.dumps({"peer": "peerFP", "endpoints": ["wss://x"]}).encode())
        _set(upstream, accept_handler)
        resp = await client.post(
            "/api/hub/friends/requests/rid-1/accept",
            json={"peer_fingerprint": "peerFP"},
        )
        assert resp.json()["state"] == "accepted"
        # Now presence is authorized and forwarded; the directory's endpoints pass
        # through verbatim.
        async def pres_handler(method, url, **kw):
            return _FakeResp(content=json.dumps({"endpoints": ["wss://x", "wss://y"]}).encode())
        _set(upstream, pres_handler)
        resp = await client.get("/api/hub/presence?peer=peerFP&username=alice")
        assert resp.status_code == 200
        assert resp.json()["endpoints"] == ["wss://x", "wss://y"]
        fwd = [c for c in captured if c["url"].endswith("/api/hub/presence?username=alice")]
        assert fwd, "presence was not forwarded to the directory"


# ---------------------------------------------------------------------------
# Milestone A2: friend-accept -> contact row + peer link + block cascade
# ---------------------------------------------------------------------------


class TestFriendAcceptContactCreation:
    """Friend-accept creates a contact row and peer link."""

    @pytest.mark.asyncio
    async def test_accept_creates_contact_row(self, client, upstream):
        """Friend-accept with identity info creates a contact row in contacts_store."""
        from tinyagentos.hub import identity as idmod

        # Ensure we have a local hub identity so the handler can run.
        idmod.load_or_create()

        # Initialise contacts_store — the lifespan may not have done this in tests.
        contacts = client._transport.app.state.contacts_store
        if contacts._db is not None:
            await contacts.close()
        await contacts.init()

        async def handler(method, url, **kw):
            return _FakeResp(content=json.dumps({
                "peer": "peerFP",
                "username": "hogne",
                "display_name": "Hogne",
                "signing_pubkey": "ab" * 32,
                "encryption_pubkey": "cd" * 32,
                "endpoints": [],
            }).encode())
        _set(upstream, handler)
        resp = await client.post(
            "/api/hub/friends/requests/rid-9/accept",
            json={"peer_fingerprint": "peerFP"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "accepted"

        # Verify the contact row was created.
        contact = await contacts.get_contact("hub:hogne")
        assert contact is not None
        assert contact["hub_username"] == "hogne"
        assert contact["display_name"] == "Hogne"
        assert contact["ed25519_pub"] == "ab" * 32
        assert contact["x25519_pub"] == "cd" * 32
        assert contact["status"] == "active"

    @pytest.mark.asyncio
    async def test_accept_creates_peer_link(self, client, upstream):
        """Friend-accept creates a peer_link with inbound token and endpoints."""
        from tinyagentos.hub import identity as idmod

        idmod.load_or_create()

        # Initialise contacts_store.
        contacts = client._transport.app.state.contacts_store
        if contacts._db is not None:
            await contacts.close()
        await contacts.init()

        async def handler(method, url, **kw):
            return _FakeResp(content=json.dumps({
                "peer": "peerFP",
                "username": "hogne",
                "display_name": "Hogne",
                "signing_pubkey": "ab" * 32,
                "encryption_pubkey": "cd" * 32,
                "endpoints": [],
            }).encode())
        _set(upstream, handler)
        resp = await client.post(
            "/api/hub/friends/requests/rid-9/accept",
            json={"peer_fingerprint": "peerFP"},
        )
        assert resp.status_code == 200

        contacts = client._transport.app.state.contacts_store
        plink = await contacts.get_peer_link("hub:hogne")
        assert plink is not None
        # inbound_token_hash should be set (non-empty)
        assert plink.get("inbound_token_hash")
        assert len(plink["inbound_token_hash"]) == 64  # SHA-256 hex
        # outbound_token starts empty (filled on handshake reply)
        assert plink["outbound_token"] == ""
        # endpoints stored as empty list when directory returns none
        assert plink["endpoints"] == []

    @pytest.mark.asyncio
    async def test_accept_no_contacts_store_does_not_crash(self, client, upstream):
        """Friend-accept without a contacts_store (e.g. uninitialised) still succeeds."""
        from tinyagentos.hub import identity as idmod

        idmod.load_or_create()

        async def handler(method, url, **kw):
            return _FakeResp(content=json.dumps({
                "peer": "peerFP",
                "username": "alice",
            }).encode())
        _set(upstream, handler)

        # Temporarily remove contacts_store to simulate missing store.
        saved = client._transport.app.state.contacts_store
        client._transport.app.state.contacts_store = None
        try:
            resp = await client.post(
                "/api/hub/friends/requests/rid-9/accept",
                json={"peer_fingerprint": "peerFP"},
            )
            assert resp.status_code == 200
            assert resp.json()["state"] == "accepted"
        finally:
            client._transport.app.state.contacts_store = saved


class TestBlockCascade:
    """Block cascades to revoke the peer link."""

    @pytest.mark.asyncio
    async def test_block_revokes_peer_link(self, client, upstream):
        """Blocking a peer whose fingerprint matches a hub author revokes their peer link."""
        from tinyagentos.hub import identity as idmod

        idmod.load_or_create()

        # Initialise contacts_store.
        contacts = client._transport.app.state.contacts_store
        if contacts._db is not None:
            await contacts.close()
        await contacts.init()

        # First accept to create the contact + peer link.
        async def accept_handler(method, url, **kw):
            return _FakeResp(content=json.dumps({
                "peer": "peerFP",
                "username": "hogne",
                "display_name": "Hogne",
                "signing_pubkey": "ab" * 32,
                "encryption_pubkey": "cd" * 32,
                "endpoints": [],
            }).encode())
        _set(upstream, accept_handler)
        resp = await client.post(
            "/api/hub/friends/requests/rid-1/accept",
            json={"peer_fingerprint": "peerFP"},
        )
        assert resp.json()["state"] == "accepted"

        # Verify peer link exists before block.
        contacts = client._transport.app.state.contacts_store
        plink = await contacts.get_peer_link("hub:hogne")
        assert plink is not None
        assert plink.get("revoked_at") is None

        # Register the hub author so get_author() resolves fingerprint → username.
        # The friend-accept handler only records the local friend edge, not an
        # author row for the peer.  Register one manually: fingerprint "peerFP"
        # (the blocked peer) → username "hogne" so the cascade finds the contact.
        from tinyagentos.hub.store import HubStore
        hub = HubStore(hub_store.default_db_path())
        await hub.init()
        try:
            await hub.upsert_author("peerFP", username="hogne")

            # Now block — should cascade to revoke_peer_link.
            captured, calls = upstream
            resp = await client.post(
                "/api/hub/friends/block",
                json={"peer_fingerprint": "peerFP"},
            )
            assert resp.json()["state"] == "blocked"

            # Verify the peer link was revoked.
            plink = await contacts.get_peer_link("hub:hogne")
            assert plink is not None
            assert plink.get("revoked_at") is not None
            # Contact status should also be revoked.
            contact = await contacts.get_contact("hub:hogne")
            assert contact is not None
            assert contact["status"] == "revoked"
        finally:
            await hub.close()
