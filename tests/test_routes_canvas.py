"""Endpoint tests for tinyagentos/routes/canvas.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_canvas_returns_200(client):
    resp = await client.post("/api/canvas/generate", json={
        "title": "Test Canvas",
        "content": "# Hello",
        "style": "dark",
        "format": "markdown",
        "agent_name": "tester",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_canvas_response_shape(client):
    resp = await client.post("/api/canvas/generate", json={
        "title": "Test Canvas",
        "content": "# Hello",
        "style": "dark",
        "format": "markdown",
        "agent_name": "tester",
    })
    data = resp.json()
    assert "canvas_id" in data
    assert "canvas_url" in data
    assert "edit_token" in data
    assert data["canvas_url"] == f"/canvas/{data['canvas_id']}"


@pytest.mark.asyncio
async def test_create_canvas_defaults(client):
    resp = await client.post("/api/canvas/generate", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert "canvas_id" in data
    assert "edit_token" in data


@pytest.mark.asyncio
async def test_get_canvas_data_returns_200(client):
    created = (await client.post("/api/canvas/generate", json={
        "title": "Fetch Me",
        "content": "some content",
    })).json()
    resp = await client.get(f"/api/canvas/{created['canvas_id']}/data")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_canvas_data_shape(client):
    created = (await client.post("/api/canvas/generate", json={
        "title": "Fetch Me",
        "content": "some content",
    })).json()
    data = (await client.get(f"/api/canvas/{created['canvas_id']}/data")).json()
    assert data["id"] == created["canvas_id"]
    assert data["title"] == "Fetch Me"
    assert data["content"] == "some content"
    assert "edit_token" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_get_canvas_not_found(client):
    resp = await client.get("/api/canvas/nonexistent/data")
    assert resp.status_code == 404
    assert resp.json()["error"] == "Canvas not found"


@pytest.mark.asyncio
async def test_update_canvas_returns_200(client):
    created = (await client.post("/api/canvas/generate", json={
        "title": "Update Me",
        "content": "old content",
    })).json()
    hub = client._transport.app.state.chat_hub
    with patch.object(hub, "broadcast", new_callable=AsyncMock):
        resp = await client.post(f"/api/canvas/{created['canvas_id']}/update", json={
            "edit_token": created["edit_token"],
            "content": "new content",
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "updated"


@pytest.mark.asyncio
async def test_update_canvas_reflects_changes(client):
    created = (await client.post("/api/canvas/generate", json={
        "title": "Update Me",
        "content": "old content",
    })).json()
    hub = client._transport.app.state.chat_hub
    with patch.object(hub, "broadcast", new_callable=AsyncMock):
        await client.post(f"/api/canvas/{created['canvas_id']}/update", json={
            "edit_token": created["edit_token"],
            "content": "new content",
            "title": "Updated Title",
        })
    data = (await client.get(f"/api/canvas/{created['canvas_id']}/data")).json()
    assert data["content"] == "new content"
    assert data["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_update_canvas_invalid_token(client):
    created = (await client.post("/api/canvas/generate", json={
        "title": "Protected",
        "content": "secret",
    })).json()
    resp = await client.post(f"/api/canvas/{created['canvas_id']}/update", json={
        "edit_token": "wrong-token",
        "content": "hacked",
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Invalid edit token or canvas not found"


@pytest.mark.asyncio
async def test_update_canvas_not_found(client):
    resp = await client.post("/api/canvas/nonexistent/update", json={
        "edit_token": "some-token",
        "content": "new",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_canvas_returns_200(client):
    created = (await client.post("/api/canvas/generate", json={
        "title": "Delete Me",
        "content": "bye",
    })).json()
    resp = await client.delete(f"/api/canvas/{created['canvas_id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_canvas_not_found(client):
    resp = await client.delete("/api/canvas/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"] == "Canvas not found"


@pytest.mark.asyncio
async def test_delete_canvas_removes_data(client):
    created = (await client.post("/api/canvas/generate", json={
        "title": "Delete Me",
        "content": "bye",
    })).json()
    await client.delete(f"/api/canvas/{created['canvas_id']}")
    resp = await client.get(f"/api/canvas/{created['canvas_id']}/data")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_canvases_returns_200(client):
    resp = await client.get("/api/canvas")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_canvases_shape(client):
    created = (await client.post("/api/canvas/generate", json={
        "title": "Listed",
        "content": "in list",
    })).json()
    data = (await client.get("/api/canvas")).json()
    assert "canvases" in data
    assert isinstance(data["canvases"], list)
    ids = [c["id"] for c in data["canvases"]]
    assert created["canvas_id"] in ids


@pytest.mark.asyncio
async def test_list_canvases_empty(client):
    """Before creating any canvases the list may be empty or contain items from
    other tests; just verify the response structure is correct."""
    resp = await client.get("/api/canvas")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["canvases"], list)


# WebSocket endpoint (/ws/canvas/{canvas_id}) requires a live WebSocket
# connection and real-time hub interaction; skipped as it needs an external
# transport not available through the async HTTP client fixture.
