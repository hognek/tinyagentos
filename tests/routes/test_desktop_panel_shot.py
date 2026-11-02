"""POST /api/desktop/panel-shot: a real on-glass screenshot via taos-shot.

taos-shot is stubbed with a fake executable shell script; nothing here needs a
handset. The app is built with an explicit tmp data_dir.
"""
from __future__ import annotations

import asyncio
import os
import stat
import time

import pytest
import pytest_asyncio
import yaml
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from tinyagentos.agent_grants_store import AgentGrantsStore
from tinyagentos.agent_registry_store import (
    AgentRegistryStore,
    load_or_create_signing_keypair,
    mint_registry_token,
)
from tinyagentos.app import create_app
from tinyagentos.auth_middleware import _AGENT_TOKEN_PATHS
from tinyagentos.native_agent_identity import ensure_native_agent_identity
from tinyagentos.routes import desktop_control
from taos_test_csrf import csrf_event_hooks

PATH = "/api/desktop/panel-shot"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-panel-bytes"


def _fake(tmp_path, body: str):
    script = tmp_path / "taos-shot"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | 0o755)
    return str(script)


def _writes_png(tmp_path):
    png = tmp_path / "fixture.png"
    png.write_bytes(PNG)
    return _fake(tmp_path, f'cp "{png}" "$1"\necho "$1"')


@pytest_asyncio.fixture
async def env(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.yaml").write_text(yaml.dump({
        "server": {"host": "0.0.0.0", "port": 6969},
        "backends": [], "qmd": {"url": "http://localhost:7832"},
        "agents": [], "metrics": {"poll_interval": 30, "retention_days": 30},
    }))
    (data / ".setup_complete").touch()
    app = create_app(data_dir=data)
    admin = app.state.auth
    if not admin.is_configured():
        admin.setup_user("admin", "Admin", "", "adminpass")
    owner = admin.find_user("admin")["id"]

    registry = AgentRegistryStore(tmp_path / "reg.db")
    await registry.init()
    grants = AgentGrantsStore(tmp_path / "grants.db")
    await grants.init()
    priv, pub = load_or_create_signing_keypair(tmp_path / "keys")
    app.state.agent_registry = registry
    app.state.agent_grants = grants
    app.state.agent_registry_keypair = (priv, pub)

    native = await ensure_native_agent_identity(
        registry=registry, grants=grants, data_dir=data,
        signing_key_pem=priv, user_id=owner,
    )
    other = await registry.register(
        framework="claude", display_name="other", user_id=owner,
        origin="taos-deployed", handle="@other",
    )
    tokens = {
        "native": mint_registry_token(native["canonical_id"], priv, user_id=owner, framework="taos-native"),
        "other": mint_registry_token(other["canonical_id"], priv, user_id=owner, framework="claude"),
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           event_hooks=csrf_event_hooks()) as client:
        client.tokens = tokens
        client.auth_mgr = admin
        client.registry, client.native_cid = registry, native["canonical_id"]
        client.mint_native = lambda: mint_registry_token(
            native["canonical_id"], priv, user_id=owner, framework="taos-native")
        yield client
    await registry.close()
    await grants.close()


def _auth(client, who):
    return {"Authorization": f"Bearer {client.tokens[who]}"}


def test_path_is_agent_token_allowlisted():
    assert PATH in _AGENT_TOKEN_PATHS


@pytest.mark.asyncio
async def test_unauthenticated_is_401(env):
    resp = await env.post(PATH)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_non_native_agent_token_is_403(env, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which", lambda _n: _writes_png(tmp_path))
    resp = await env.post(PATH, headers=_auth(env, "other"))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_no_taos_shot_is_404(env, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which", lambda _n: None)
    resp = await env.post(PATH, headers=_auth(env, "native"))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "no panel on this host"}


@pytest.mark.asyncio
async def test_success_returns_exact_png_and_removes_tempdir(env, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which", lambda _n: _writes_png(tmp_path))
    made = []
    real = desktop_control.tempfile.mkdtemp

    def rec(*a, **k):
        d = real(*a, **k)
        made.append(d)
        return d

    monkeypatch.setattr(desktop_control.tempfile, "mkdtemp", rec)
    resp = await env.post(PATH, headers=_auth(env, "native"))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == PNG
    assert len(made) == 1
    assert not os.path.exists(made[0])


@pytest.mark.asyncio
async def test_timeout_is_504_and_cleans_up(env, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which", lambda _n: _fake(tmp_path, "sleep 30"))
    monkeypatch.setattr(desktop_control, "_PANEL_SHOT_TIMEOUT", 0.5)
    made = []
    real = desktop_control.tempfile.mkdtemp
    monkeypatch.setattr(desktop_control.tempfile, "mkdtemp",
                        lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    resp = await env.post(PATH, headers=_auth(env, "native"))
    assert resp.status_code == 504
    assert not os.path.exists(made[0])


@pytest.mark.asyncio
async def test_nonzero_exit_is_502_without_stderr(env, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which",
                        lambda _n: _fake(tmp_path, 'echo secret-stderr >&2\nexit 3'))
    resp = await env.post(PATH, headers=_auth(env, "native"))
    assert resp.status_code == 502
    assert "secret-stderr" not in resp.text


@pytest.mark.asyncio
async def test_missing_output_is_502(env, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which", lambda _n: _fake(tmp_path, "exit 0"))
    resp = await env.post(PATH, headers=_auth(env, "native"))
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_concurrent_call_is_429(env, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which", lambda _n: _fake(tmp_path, "sleep 2"))
    first = asyncio.create_task(env.post(PATH, headers=_auth(env, "native")))
    for _ in range(100):
        await asyncio.sleep(0.05)
        if desktop_control._PANEL_SHOT_LOCK.locked():
            break
    second = await env.post(PATH, headers=_auth(env, "native"))
    assert second.status_code == 429
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
async def test_native_token_superseded_by_rotation_is_403(env, tmp_path, monkeypatch):
    ran = tmp_path / "ran"
    png = tmp_path / "fixture.png"
    png.write_bytes(PNG)
    monkeypatch.setattr(desktop_control.shutil, "which",
                        lambda _n: _fake(tmp_path, f'touch "{ran}"\ncp "{png}" "$1"'))
    old = env.tokens["native"]
    await env.registry.bump_token_min_iat(env.native_cid, int(time.time()) + 3600)
    resp = await env.post(PATH, headers={"Authorization": f"Bearer {old}"})
    assert resp.status_code == 403
    assert not ran.exists()


@pytest.mark.asyncio
async def test_native_token_minted_after_rotation_still_captures(env, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which", lambda _n: _writes_png(tmp_path))
    await env.registry.bump_token_min_iat(env.native_cid, int(time.time()))
    resp = await env.post(PATH, headers={"Authorization": f"Bearer {env.mint_native()}"})
    assert resp.status_code == 200
    assert resp.content == PNG


@pytest.mark.asyncio
async def test_cancelled_request_kills_taos_shot_and_releases_lock(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    monkeypatch.setattr(desktop_control.shutil, "which",
                        lambda _n: _fake(tmp_path, f'echo $$ > "{pidfile}"\nexec sleep 30'))
    req = Request({"type": "http", "method": "POST", "path": PATH, "headers": [],
                   "state": {"via": "registry_jwt_native_agent"}})
    task = asyncio.create_task(desktop_control.panel_shot(req))
    for _ in range(100):
        await asyncio.sleep(0.05)
        if pidfile.exists() and pidfile.read_text().strip():
            break
    pid = int(pidfile.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    if alive:
        os.kill(pid, 9)
    assert not alive
    assert not desktop_control._PANEL_SHOT_LOCK.locked()


def _session(client, username):
    auth = client.auth_mgr
    if username != "admin":
        code = auth.add_user_invite(username, "admin")
        auth.complete_invite(username, code, username, "", "testpass1")
    uid = auth.find_user(username)["id"]
    return {"Cookie": f"taos_session={auth.create_session(user_id=uid, long_lived=True)}"}


@pytest.mark.asyncio
async def test_non_admin_session_is_403(env, tmp_path, monkeypatch):
    ran = tmp_path / "ran"
    png = tmp_path / "fixture.png"
    png.write_bytes(PNG)
    monkeypatch.setattr(desktop_control.shutil, "which",
                        lambda _n: _fake(tmp_path, f'touch "{ran}"\ncp "{png}" "$1"'))
    resp = await env.post(PATH, headers=_session(env, "guest"))
    assert resp.status_code == 403
    assert not ran.exists()


@pytest.mark.asyncio
async def test_admin_session_captures(env, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_control.shutil, "which", lambda _n: _writes_png(tmp_path))
    resp = await env.post(PATH, headers=_session(env, "admin"))
    assert resp.status_code == 200
    assert resp.content == PNG
