"""Endpoint tests for tinyagentos/routes/catalog.py."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestCatalogStats:
    async def test_stats_returns_200(self, client):
        resp = await client.get("/api/memory/catalog/stats")
        assert resp.status_code == 200

    async def test_stats_returns_dict(self, client):
        data = (await client.get("/api/memory/catalog/stats")).json()
        assert isinstance(data, dict)

    async def test_stats_has_expected_keys(self, client):
        data = (await client.get("/api/memory/catalog/stats")).json()
        for key in ("total_sessions", "total_sub_sessions", "days_cataloged"):
            assert key in data, f"missing key: {key}"

    async def test_stats_empty_catalog(self, client):
        data = (await client.get("/api/memory/catalog/stats")).json()
        assert data["total_sessions"] == 0
        assert data["total_sub_sessions"] == 0


@pytest.mark.asyncio
class TestCatalogDate:
    async def test_date_returns_200(self, client):
        resp = await client.get("/api/memory/catalog/date/2026-06-19")
        assert resp.status_code == 200

    async def test_date_returns_list(self, client):
        data = (await client.get("/api/memory/catalog/date/2026-06-19")).json()
        assert isinstance(data, list)

    async def test_date_empty_for_unknown_date(self, client):
        data = (await client.get("/api/memory/catalog/date/2000-01-01")).json()
        assert data == []


@pytest.mark.asyncio
class TestCatalogRange:
    async def test_range_returns_200(self, client):
        resp = await client.get(
            "/api/memory/catalog/range",
            params={"start": "2026-06-01", "end": "2026-06-30"},
        )
        assert resp.status_code == 200

    async def test_range_returns_list(self, client):
        data = (
            await client.get(
                "/api/memory/catalog/range",
                params={"start": "2026-06-01", "end": "2026-06-30"},
            )
        ).json()
        assert isinstance(data, list)

    async def test_range_empty_for_future_dates(self, client):
        data = (
            await client.get(
                "/api/memory/catalog/range",
                params={"start": "2099-01-01", "end": "2099-12-31"},
            )
        ).json()
        assert data == []


@pytest.mark.asyncio
class TestCatalogSearch:
    async def test_search_returns_200(self, client):
        resp = await client.get("/api/memory/catalog/search", params={"q": "test"})
        assert resp.status_code == 200

    async def test_search_returns_list(self, client):
        data = (
            await client.get("/api/memory/catalog/search", params={"q": "test"})
        ).json()
        assert isinstance(data, list)

    async def test_search_empty_for_no_match(self, client):
        data = (
            await client.get(
                "/api/memory/catalog/search", params={"q": "zzzznonexistent"}
            )
        ).json()
        assert data == []

    async def test_search_respects_limit(self, client):
        data = (
            await client.get(
                "/api/memory/catalog/search", params={"q": "a", "limit": 5}
            )
        ).json()
        assert len(data) <= 5


@pytest.mark.asyncio
class TestCatalogSession:
    async def test_session_not_found_returns_404(self, client):
        resp = await client.get("/api/memory/catalog/session/99999")
        assert resp.status_code == 404

    async def test_session_not_found_error_message(self, client):
        data = (await client.get("/api/memory/catalog/session/99999")).json()
        assert "detail" in data


@pytest.mark.asyncio
class TestCatalogSessionContext:
    async def test_context_not_found_returns_404(self, client):
        resp = await client.get("/api/memory/catalog/session/99999/context")
        assert resp.status_code == 404

    async def test_context_not_found_error_message(self, client):
        data = (await client.get("/api/memory/catalog/session/99999/context")).json()
        assert "detail" in data


@pytest.mark.asyncio
class TestCatalogRecent:
    async def test_recent_returns_200(self, client):
        resp = await client.get("/api/memory/catalog/recent")
        assert resp.status_code == 200

    async def test_recent_returns_list(self, client):
        data = (await client.get("/api/memory/catalog/recent")).json()
        assert isinstance(data, list)

    async def test_recent_empty_catalog(self, client):
        data = (await client.get("/api/memory/catalog/recent")).json()
        assert data == []

    async def test_recent_respects_limit(self, client):
        data = (await client.get("/api/memory/catalog/recent", params={"limit": 5})).json()
        assert len(data) <= 5


# POST /api/memory/catalog/index and POST /api/memory/catalog/rebuild are
# skipped: they create a CatalogPipeline that depends on archive files and
# potentially an LLM service, which are not available in the test fixture.
