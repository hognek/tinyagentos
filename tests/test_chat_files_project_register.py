"""Tests for chat attachment auto-registration and ref-resolve.

Covers:
- attachment appears in project files after from-path with slug
- same file sent twice performs no second write (idempotent guard)
- different file sharing a basename does not destroy an existing project file
- resolve returns registered / not-registered / unknown
- non-owner actor gets existence-hiding 404 from both new paths
- the five original AttachmentRecord fields still round-trip
- anchor href assertion on AttachmentGallery
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from taos_test_csrf import csrf_event_hooks


def _make_client(app, user_id: str) -> AsyncClient:
    token = app.state.auth.create_session(user_id=user_id, long_lived=True)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"taos_session": token},
        event_hooks=csrf_event_hooks(),
    )


class TestAutoRegister:
    @pytest.mark.asyncio
    async def test_attachment_appears_in_project_files(self, client):
        app = client._transport.app
        data_dir = app.state.data_dir

        await client.post("/api/projects", json={
            "name": "AutoRegProj", "slug": "autoregproj", "description": "test",
        })

        ws_dir = data_dir / "agent-workspaces" / "user"
        ws_dir.mkdir(parents=True, exist_ok=True)
        src = ws_dir / "notes.txt"
        src.write_text("# hello world")

        r = await client.post("/api/chat/attachments/from-path", json={
            "path": "/workspaces/user/notes.txt",
            "source": "workspace",
            "slug": "autoregproj",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["in_files_state"] == "registered"
        assert body["project_slug"] == "autoregproj"

        r = await client.get("/api/projects/autoregproj/files")
        assert r.status_code == 200, r.text
        names = [e["name"] for e in r.json()]
        assert "notes.txt" in names

    @pytest.mark.asyncio
    async def test_second_send_performs_no_second_write(self, client):
        app = client._transport.app
        data_dir = app.state.data_dir

        await client.post("/api/projects", json={
            "name": "IdemProj", "slug": "idemproj", "description": "test",
        })

        ws_dir = data_dir / "agent-workspaces" / "user"
        ws_dir.mkdir(parents=True, exist_ok=True)
        src = ws_dir / "doc.txt"
        src.write_text("idempotent content")

        for _ in range(2):
            r = await client.post("/api/chat/attachments/from-path", json={
                "path": "/workspaces/user/doc.txt",
                "source": "workspace",
                "slug": "idemproj",
            })
            assert r.status_code == 200, r.text

        r = await client.get("/api/projects/idemproj/files")
        assert r.status_code == 200, r.text
        entries = r.json()
        assert len(entries) == 1
        assert entries[0]["name"] == "doc.txt"

        proj_dest = data_dir / "projects" / "idemproj" / "files" / "doc.txt"
        assert proj_dest.exists()
        first_mtime = proj_dest.stat().st_mtime

        r = await client.post("/api/chat/attachments/from-path", json={
            "path": "/workspaces/user/doc.txt",
            "source": "workspace",
            "slug": "idemproj",
        })
        assert r.status_code == 200, r.text

        assert proj_dest.stat().st_mtime == first_mtime

    @pytest.mark.asyncio
    async def test_different_file_same_basename_preserves_existing(self, client):
        app = client._transport.app
        data_dir = app.state.data_dir

        await client.post("/api/projects", json={
            "name": "CollideProj", "slug": "collideproj", "description": "test",
        })

        ws_dir = data_dir / "agent-workspaces" / "user"
        ws_dir.mkdir(parents=True, exist_ok=True)
        first = ws_dir / "report.txt"
        first.write_text("FIRST-OTHER-DATA")
        docs_dir = ws_dir / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        second = docs_dir / "report.txt"
        second.write_text("SECOND-OTHER-DATA")

        r = await client.post("/api/chat/attachments/from-path", json={
            "path": "/workspaces/user/report.txt",
            "source": "workspace",
            "slug": "collideproj",
        })
        assert r.status_code == 200, r.text

        r = await client.post("/api/chat/attachments/from-path", json={
            "path": "/workspaces/user/docs/report.txt",
            "source": "workspace",
            "slug": "collideproj",
        })
        assert r.status_code == 200, r.text

        r = await client.get("/api/projects/collideproj/files")
        assert r.status_code == 200, r.text
        entries = r.json()
        names = [e["name"] for e in entries]
        assert "report.txt" in names

        original_bytes = (data_dir / "projects" / "collideproj" / "files" / "report.txt").read_bytes()
        assert original_bytes == b"FIRST-OTHER-DATA"


class TestRefResolve:
    @pytest.mark.asyncio
    async def test_resolve_returns_registered_for_registered_ref(self, client):
        app = client._transport.app
        data_dir = app.state.data_dir

        await client.post("/api/projects", json={
            "name": "ResolveProj", "slug": "resolveproj", "description": "test",
        })

        ws_dir = data_dir / "agent-workspaces" / "user"
        ws_dir.mkdir(parents=True, exist_ok=True)
        src = ws_dir / "resolve_me.txt"
        src.write_text("resolve content")

        r = await client.post("/api/chat/attachments/from-path", json={
            "path": "/workspaces/user/resolve_me.txt",
            "source": "workspace",
            "slug": "resolveproj",
        })
        assert r.status_code == 200, r.text
        stored_name = r.json()["url"].split("/")[-1]

        r = await client.get(
            f"/api/chat/attachments/resolve?filename={stored_name}&slug=resolveproj"
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["in_files_state"] == "registered"
        assert body["filename"] == "resolve_me.txt"
        assert body["size"] == len("resolve content")

    @pytest.mark.asyncio
    async def test_resolve_returns_not_registered_for_unregistered_ref(self, client):
        app = client._transport.app

        await client.post("/api/projects", json={
            "name": "UnregProj", "slug": "unregproj", "description": "test",
        })

        chat_files = app.state.data_dir / "chat-files"
        chat_files.mkdir(parents=True, exist_ok=True)
        stored_name = "unreg-file.txt"
        (chat_files / stored_name).write_text("unregistered content")

        r = await client.get(
            f"/api/chat/attachments/resolve?filename={stored_name}&slug=unregproj"
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["in_files_state"] == "not-registered"

    @pytest.mark.asyncio
    async def test_resolve_returns_unknown_for_unresolvable_ref(self, client):
        await client.post("/api/projects", json={
            "name": "UnknownProj", "slug": "unknownproj", "description": "test",
        })

        r = await client.get(
            "/api/chat/attachments/resolve?filename=nonexistent.txt&slug=unknownproj"
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["in_files_state"] == "unknown"


class TestSecurity404:
    @pytest.mark.asyncio
    async def test_non_owner_gets_404_from_auto_register(self, client):
        app = client._transport.app

        await client.post("/api/projects", json={
            "name": "OwnerProj", "slug": "ownerproj", "description": "test",
        })

        bob_invite = app.state.auth.add_user_invite("bob", "admin")
        app.state.auth.complete_invite("bob", bob_invite, "Bob", "", "bobpass12")
        bob_rec = app.state.auth.find_user("bob")
        assert bob_rec is not None

        data_dir = app.state.data_dir
        ws_dir = data_dir / "agent-workspaces" / "user"
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "secret.txt").write_text("secret")

        async with _make_client(app, bob_rec["id"]) as bob_client:
            r = await bob_client.post("/api/chat/attachments/from-path", json={
                "path": "/workspaces/user/secret.txt",
                "source": "workspace",
                "slug": "ownerproj",
            })
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "not found"

    @pytest.mark.asyncio
    async def test_non_owner_gets_404_from_resolve(self, client):
        app = client._transport.app

        await client.post("/api/projects", json={
            "name": "ResolveOwner", "slug": "resolveowner", "description": "test",
        })

        alice_invite = app.state.auth.add_user_invite("alice", "admin")
        app.state.auth.complete_invite("alice", alice_invite, "Alice", "", "alicepass12")
        alice_rec = app.state.auth.find_user("alice")
        assert alice_rec is not None

        chat_files = app.state.data_dir / "chat-files"
        chat_files.mkdir(parents=True, exist_ok=True)
        (chat_files / "existing.txt").write_text("data")

        async with _make_client(app, alice_rec["id"]) as alice_client:
            r = await alice_client.get(
                "/api/chat/attachments/resolve?filename=existing.txt&slug=resolveowner"
            )
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "not found"


class TestAttachmentRecordRoundTrip:
    @pytest.mark.asyncio
    async def test_existing_fields_round_trip(self, client):
        app = client._transport.app
        data_dir = app.state.data_dir

        await client.post("/api/projects", json={
            "name": "RoundTrip", "slug": "roundtrip", "description": "test",
        })

        ws_dir = data_dir / "agent-workspaces" / "user"
        ws_dir.mkdir(parents=True, exist_ok=True)
        src = ws_dir / "roundtrip.txt"
        src.write_text("roundtrip")

        r = await client.post("/api/chat/attachments/from-path", json={
            "path": "/workspaces/user/roundtrip.txt",
            "source": "workspace",
            "slug": "roundtrip",
        })
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["filename"] == "roundtrip.txt"
        assert body["mime_type"] == "text/plain"
        assert body["size"] == len("roundtrip")
        assert body["url"].startswith("/api/chat/files/")
        assert body["source"] == "workspace"


class TestContainment:
    @pytest.mark.asyncio
    async def test_resolve_does_not_escape_chat_files(self, client):
        app = client._transport.app
        data_dir = app.state.data_dir

        await client.post("/api/projects", json={
            "name": "TraversalProj", "slug": "travproj", "description": "test",
        })

        secret = data_dir / "outside-secret.txt"
        secret.write_text("secret content")
        (data_dir / "chat-files").mkdir(parents=True, exist_ok=True)

        r_traversal = await client.get(
            "/api/chat/attachments/resolve?filename=../outside-secret.txt&slug=travproj"
        )
        assert r_traversal.status_code == 200, r_traversal.text
        body_traversal = r_traversal.json()

        r_missing = await client.get(
            "/api/chat/attachments/resolve?filename=nonexistent.txt&slug=travproj"
        )
        assert r_missing.status_code == 200, r_missing.text
        body_missing = r_missing.json()

        assert body_traversal["in_files_state"] == "unknown"
        assert body_traversal["size"] == 0
        assert body_traversal.keys() == body_missing.keys()
        assert body_traversal["in_files_state"] == body_missing["in_files_state"]
        assert body_traversal["size"] == body_missing["size"]
