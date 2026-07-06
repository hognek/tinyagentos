"""Tests for the read-only taOSmd A2A coordination bus proxy (routes/a2a_bus.py).

The outbound bus calls are mocked with respx (already in dev deps). The bus URL
defaults to http://127.0.0.1:7900; we pin it via TAOS_A2A_BUS_URL so the mocked
routes match deterministically.
"""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from tinyagentos.app import create_app

_BUS = "http://bus.test"


@pytest.fixture(autouse=True)
def _pin_bus_url(monkeypatch):
    monkeypatch.setenv("TAOS_A2A_BUS_URL", _BUS)


def test_bus_routes_registered():
    """Both read-only bus endpoints are registered; no send/post path exists."""
    app = create_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/a2a/bus/channels" in paths
    assert "/api/a2a/bus/messages" in paths


@pytest.mark.asyncio
@respx.mock
async def test_channels_proxied_and_sorted(client):
    """Channels are proxied and sorted by last_ts descending, available:true."""
    respx.get(f"{_BUS}/a2a/channels").mock(
        return_value=Response(
            200,
            json={
                "channels": [
                    {"channel": "old", "members": ["a"], "message_count": 1,
                     "created_ts": 1.0, "last_ts": 100.0},
                    {"channel": "new", "members": ["a", "b"], "message_count": 5,
                     "created_ts": 2.0, "last_ts": 300.0},
                    {"channel": "mid", "members": ["b"], "message_count": 2,
                     "created_ts": 3.0, "last_ts": 200.0},
                ]
            },
        )
    )

    resp = await client.get("/api/a2a/bus/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert [c["channel"] for c in body["channels"]] == ["new", "mid", "old"]


@pytest.mark.asyncio
@respx.mock
async def test_channels_bus_unreachable_is_offline(client):
    """Bus connection error -> available:false, empty list, HTTP 200."""
    respx.get(f"{_BUS}/a2a/channels").mock(
        side_effect=httpx_connect_error()
    )

    resp = await client.get("/api/a2a/bus/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["channels"] == []


@pytest.mark.asyncio
@respx.mock
async def test_channels_bus_non_200_is_offline(client):
    """Bus 500 -> available:false, empty list, HTTP 200."""
    respx.get(f"{_BUS}/a2a/channels").mock(return_value=Response(500))

    resp = await client.get("/api/a2a/bus/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["channels"] == []


@pytest.mark.asyncio
@respx.mock
async def test_messages_maps_channel_to_thread_and_clamps_limit(client):
    """channel maps to the bus thread param and limit is clamped to 500."""
    route = respx.get(f"{_BUS}/a2a/messages").mock(
        return_value=Response(
            200,
            json={
                "messages": [
                    {"id": 1, "ts": 10.0, "from": "@taOS", "body": "hi",
                     "thread": "ops", "reply_to": None},
                ]
            },
        )
    )

    resp = await client.get("/api/a2a/bus/messages", params={"channel": "ops", "limit": 9999})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["messages"][0]["from"] == "@taOS"

    sent = route.calls.last.request
    assert sent.url.params["thread"] == "ops"
    assert sent.url.params["limit"] == "500"


@pytest.mark.asyncio
async def test_messages_missing_channel_is_400(client):
    """No channel -> 400 with an error payload, no bus call attempted."""
    resp = await client.get("/api/a2a/bus/messages")
    assert resp.status_code == 400
    assert resp.json() == {"error": "channel required"}


@pytest.mark.asyncio
@respx.mock
async def test_messages_bus_error_is_offline(client):
    """Bus error on messages -> available:false, empty list, HTTP 200."""
    respx.get(f"{_BUS}/a2a/messages").mock(side_effect=httpx_connect_error())

    resp = await client.get("/api/a2a/bus/messages", params={"channel": "ops"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["messages"] == []


def httpx_connect_error():
    import httpx

    return httpx.ConnectError("connection refused")
