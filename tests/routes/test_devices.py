import pytest


@pytest.mark.asyncio
class TestDeviceRoutes:
    async def test_register_returns_scoped_token_and_scopes_to_session_user(self, client):
        resp = await client.post(
            "/api/devices/register",
            json={"platform": "ios", "display_name": "iPhone", "user_id": "attacker"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["platform"] == "ios"
        assert body["scoped_token"].startswith("taosdev_")
        # Body user_id is ignored; the session user owns the device.
        assert body["user_id"] != "attacker"

    async def test_list_hides_scoped_token(self, client):
        await client.post("/api/devices/register", json={"platform": "ios"})
        resp = await client.get("/api/devices")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert "scoped_token" not in items[0]

    async def test_update_push_token(self, client):
        reg = (await client.post("/api/devices/register", json={"platform": "ios"})).json()
        resp = await client.patch(
            f"/api/devices/{reg['device_id']}/push-token", json={"push_token": "abc123"}
        )
        assert resp.status_code == 200
        assert resp.json()["push_token"] == "abc123"
        assert "scoped_token" not in resp.json()

    async def test_revoke_then_absent_from_list(self, client):
        reg = (await client.post("/api/devices/register", json={"platform": "ios"})).json()
        resp = await client.delete(f"/api/devices/{reg['device_id']}")
        assert resp.status_code == 200 and resp.json()["revoked"] is True
        assert (await client.get("/api/devices")).json()["items"] == []

    async def test_cannot_touch_another_users_device(self, client, app):
        # Register a device owned by a different user directly in the store.
        other = await app.state.device_store.register(user_id="someone-else", platform="ios")
        assert (await client.delete(f"/api/devices/{other['device_id']}")).status_code == 404
        assert (
            await client.patch(
                f"/api/devices/{other['device_id']}/push-token", json={"push_token": "x"}
            )
        ).status_code == 404
