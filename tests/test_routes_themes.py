import pytest


class TestThemesRoutes:
    @pytest.mark.asyncio
    async def test_list_themes_returns_200_and_list(self, client):
        resp = await client.get("/api/themes")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_theme_returns_200_with_removed_false(self, client):
        resp = await client.delete("/api/themes/nonexistent-theme-xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["removed"] is False

    @pytest.mark.asyncio
    async def test_install_theme_empty_body_returns_422(self, client):
        resp = await client.post("/api/themes/install")
        assert resp.status_code == 422
