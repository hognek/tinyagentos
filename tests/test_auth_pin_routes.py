"""PIN sign-in at the HTTP layer.

`test_auth_pin.py` proves the origin RULE in isolation. These tests prove the
routes actually APPLY it — a correct rule that no endpoint consults would pass
every unit test in the other file while leaving the door open.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tinyagentos.auth import AuthManager


@pytest.fixture(autouse=True)
def _clean_pin_throttle():
    """The route module's PIN limiter is a process-wide singleton (correct for a
    real deployment, which is one process). Reset it around every test so one
    test's deliberate failures cannot throttle the next one."""
    from tinyagentos.routes import auth as auth_routes

    auth_routes._pin_limiter = type(auth_routes._pin_limiter)()
    yield
    auth_routes._pin_limiter = type(auth_routes._pin_limiter)()


@pytest.fixture()
def pin_app(tmp_path, monkeypatch):
    from tinyagentos.app import create_app

    monkeypatch.setenv("TINYAGENTOS_DATA_DIR", str(tmp_path))
    app = create_app()
    mgr = AuthManager(tmp_path)
    mgr.setup_user("tester", "Bring-up Test", "", "correct horse battery staple")
    mgr.set_pin("tester", "4913")
    app.state.auth = mgr
    return app


@pytest_asyncio.fixture()
async def console(pin_app):
    """A client that looks like the device's own screen."""
    transport = ASGITransport(app=pin_app, client=("127.0.0.1", 51234))
    async with AsyncClient(transport=transport, base_url="http://localhost:6969") as c:
        yield c


@pytest_asyncio.fixture()
async def lan(pin_app):
    """A client on the home network, i.e. NOT the console."""
    transport = ASGITransport(app=pin_app, client=("192.168.1.10", 51234))
    async with AsyncClient(transport=transport, base_url="http://taos.local:6969") as c:
        yield c


class TestPinLoginIsConsoleOnly:
    """The refusing direction, measured over HTTP."""

    @pytest.mark.asyncio
    async def test_correct_pin_from_lan_is_refused(self, lan):
        r = await lan.post("/auth/pin-login", json={"username": "tester", "pin": "4913"})
        assert r.status_code == 404
        assert "taos_session" not in r.cookies

    @pytest.mark.asyncio
    async def test_correct_pin_from_console_signs_in(self, console):
        r = await console.post("/auth/pin-login", json={"username": "tester", "pin": "4913"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.cookies.get("taos_session")

    @pytest.mark.asyncio
    async def test_forwarded_console_request_is_refused(self, console):
        """A proxied request reaches the app from loopback; it is not the console."""
        r = await console.post(
            "/auth/pin-login",
            json={"username": "tester", "pin": "4913"},
            headers={"X-Forwarded-For": "192.168.1.10"},
        )
        assert r.status_code == 404
        assert "taos_session" not in r.cookies

    @pytest.mark.asyncio
    async def test_lan_cannot_spoof_its_way_to_console(self, lan):
        r = await lan.post(
            "/auth/pin-login",
            json={"username": "tester", "pin": "4913"},
            headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_offconsole_refusal_does_not_reveal_that_a_pin_exists(self, lan):
        """404 for 'no PIN here' and 404 for 'not allowed' must be the same answer."""
        r = await lan.post("/auth/pin-login", json={"username": "tester", "pin": "4913"})
        body = r.text.lower()
        assert "incorrect" not in body
        assert "too many" not in body


class TestPinLoginCredentialChecks:
    @pytest.mark.asyncio
    async def test_wrong_pin_from_console_is_401(self, console):
        r = await console.post("/auth/pin-login", json={"username": "tester", "pin": "0000"})
        assert r.status_code == 401
        assert "taos_session" not in r.cookies

    @pytest.mark.asyncio
    async def test_password_is_not_accepted_as_a_pin(self, console):
        r = await console.post(
            "/auth/pin-login",
            json={"username": "tester", "pin": "correct horse battery staple"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_throttle_engages_and_reports_retry_after(self, console):
        for _ in range(5):
            await console.post("/auth/pin-login", json={"username": "tester", "pin": "0000"})
        r = await console.post("/auth/pin-login", json={"username": "tester", "pin": "0000"})
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) > 0

    @pytest.mark.asyncio
    async def test_throttle_blocks_even_the_correct_pin(self, console):
        """Otherwise the delay is trivially bypassed by guessing correctly."""
        for _ in range(5):
            await console.post("/auth/pin-login", json={"username": "tester", "pin": "0000"})
        r = await console.post("/auth/pin-login", json={"username": "tester", "pin": "4913"})
        assert r.status_code == 429

    @pytest.mark.asyncio
    async def test_pin_failures_do_not_lock_out_the_password(self, console):
        """R4 over HTTP: the two factors must not share a lockout budget."""
        for _ in range(12):
            await console.post("/auth/pin-login", json={"username": "tester", "pin": "0000"})
        r = await console.post(
            "/auth/login",
            json={"username": "tester", "password": "correct horse battery staple"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestStatusAdvertisesPin:
    @pytest.mark.asyncio
    async def test_console_is_offered_the_keypad(self, console):
        r = await console.get("/auth/status")
        assert r.json()["pin_available"] is True

    @pytest.mark.asyncio
    async def test_lan_is_not_told_a_pin_exists(self, lan):
        r = await lan.get("/auth/status")
        assert r.json()["pin_available"] is False

    @pytest.mark.asyncio
    async def test_forwarded_request_is_not_offered_the_keypad(self, console):
        r = await console.get("/auth/status", headers={"X-Forwarded-For": "192.168.1.10"})
        assert r.json()["pin_available"] is False

    @pytest.mark.asyncio
    async def test_no_pin_configured_is_not_advertised(self, pin_app, console):
        pin_app.state.auth.clear_pin("tester")
        r = await console.get("/auth/status")
        assert r.json()["pin_available"] is False
