"""Endpoint tests for tinyagentos/routes/knowledge.py (read endpoints)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
class TestListItems:
    async def test_list_items_returns_200_with_shape(self, client, monkeypatch):
        mock_store = AsyncMock()
        mock_store.list_items.return_value = []
        monkeypatch.setattr(client._transport.app.state, "knowledge_store", mock_store)
        resp = await client.get("/api/knowledge/items")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "count" in data
        assert data["count"] == 0

    async def test_list_items_returns_seeded_items(self, client, monkeypatch):
        mock_store = AsyncMock()
        mock_store.list_items.return_value = [
            {"id": "item-1", "title": "Test", "status": "done"},
        ]
        monkeypatch.setattr(client._transport.app.state, "knowledge_store", mock_store)
        resp = await client.get("/api/knowledge/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["id"] == "item-1"


@pytest.mark.asyncio
class TestGetItem:
    async def test_get_item_not_found(self, client, monkeypatch):
        mock_store = AsyncMock()
        mock_store.get_item.return_value = None
        monkeypatch.setattr(client._transport.app.state, "knowledge_store", mock_store)
        resp = await client.get("/api/knowledge/items/unknown-id-1234")
        assert resp.status_code == 404

    async def test_get_item_returns_item(self, client, monkeypatch):
        mock_store = AsyncMock()
        mock_store.get_item.return_value = {
            "id": "item-1", "title": "Test", "status": "done",
        }
        monkeypatch.setattr(client._transport.app.state, "knowledge_store", mock_store)
        resp = await client.get("/api/knowledge/items/item-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "item-1"


@pytest.mark.asyncio
class TestListRules:
    async def test_list_rules_returns_200(self, client, monkeypatch):
        mock_store = AsyncMock()
        mock_store.list_rules.return_value = []
        monkeypatch.setattr(client._transport.app.state, "knowledge_store", mock_store)
        resp = await client.get("/api/knowledge/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert "rules" in data

    async def test_list_rules_returns_seeded_rules(self, client, monkeypatch):
        mock_store = AsyncMock()
        mock_store.list_rules.return_value = [
            {"id": 1, "pattern": "test-*", "match_on": "title", "category": "tests", "priority": 10},
        ]
        monkeypatch.setattr(client._transport.app.state, "knowledge_store", mock_store)
        resp = await client.get("/api/knowledge/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rules"]) == 1
        assert data["rules"][0]["pattern"] == "test-*"


@pytest.mark.asyncio
class TestDeleteItem:
    async def test_delete_item_not_found(self, client, monkeypatch):
        mock_store = AsyncMock()
        mock_store.get_item.return_value = None
        monkeypatch.setattr(client._transport.app.state, "knowledge_store", mock_store)
        resp = await client.delete("/api/knowledge/items/unknown-id-5678")
        assert resp.status_code == 404
