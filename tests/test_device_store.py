import pytest
import pytest_asyncio
from tinyagentos.device_store import DeviceStore, DEVICE_TOKEN_PREFIX


@pytest_asyncio.fixture
async def store(tmp_path):
    s = DeviceStore(tmp_path / "devices.db")
    await s.init()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_register_mints_scoped_token_and_persists(store):
    dev = await store.register(user_id="u1", platform="ios", display_name="iPhone")
    assert dev["device_id"]
    assert dev["user_id"] == "u1"
    assert dev["platform"] == "ios"
    assert dev["display_name"] == "iPhone"
    assert dev["scoped_token"].startswith(DEVICE_TOKEN_PREFIX)
    assert dev["revoked"] == 0
    assert int(dev["registered_at"]) > 0

    fetched = await store.get(dev["device_id"])
    assert fetched["scoped_token"] == dev["scoped_token"]


@pytest.mark.asyncio
async def test_get_by_token_resolves_then_stops_after_revoke(store):
    dev = await store.register(user_id="u1", platform="ios")
    assert (await store.get_by_token(dev["scoped_token"]))["device_id"] == dev["device_id"]
    assert await store.get_by_token("taosdev_nope") is None

    assert await store.revoke(dev["device_id"]) is True
    assert await store.get_by_token(dev["scoped_token"]) is None


@pytest.mark.asyncio
async def test_list_for_user_scopes_and_hides_token(store):
    a = await store.register(user_id="u1", platform="ios")
    await store.register(user_id="u2", platform="ios")
    revoked = await store.register(user_id="u1", platform="watchos")
    await store.revoke(revoked["device_id"])

    rows = await store.list_for_user("u1")
    assert [r["device_id"] for r in rows] == [a["device_id"]]
    assert "scoped_token" not in rows[0]


@pytest.mark.asyncio
async def test_update_push_token(store):
    dev = await store.register(user_id="u1", platform="ios", push_token="old")
    updated = await store.update_push_token(dev["device_id"], "new")
    assert updated["push_token"] == "new"
    assert (await store.get(dev["device_id"]))["push_token"] == "new"
