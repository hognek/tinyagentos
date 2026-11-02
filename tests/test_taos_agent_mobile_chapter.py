"""The taOS Agent manual gains a phone chapter only on a mobile device.

docs/agent-manual/mobile/15-mobile.md sits in a subdirectory so the desktop
manual build (scripts/build-agent-manual.py globs [0-9]*.md, not recursive)
never includes it; the chat route appends it when the effective device class
is "mobile". A persona override still replaces the whole prompt.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
import yaml
from httpx import ASGITransport, AsyncClient

import tinyagentos.routes.taos_agent as ta_module
from tinyagentos.app import create_app
from tinyagentos.taos_agent_runtime import FrameworkDecision
from taos_test_csrf import csrf_event_hooks

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAPTER_PATH = REPO_ROOT / "docs" / "agent-manual" / "mobile" / "15-mobile.md"


def _chapter_heading() -> str:
    first = CHAPTER_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# "), first
    return first


def test_chapter_exists_outside_the_desktop_manual_glob():
    assert CHAPTER_PATH.is_file()
    heading = _chapter_heading()
    desktop_manual = (REPO_ROOT / "docs" / "taos-agent-manual.md").read_text(encoding="utf-8")
    assert heading not in desktop_manual


def test_desktop_class_prompt_has_no_mobile_chapter():
    prompt = ta_module._system_prompt_for("", "desktop")
    assert prompt == (ta_module.SYSTEM_PROMPT or None)
    assert _chapter_heading() not in (prompt or "")


def test_unknown_class_prompt_has_no_mobile_chapter():
    prompt = ta_module._system_prompt_for("", None)
    assert _chapter_heading() not in (prompt or "")


def test_mobile_class_prompt_appends_the_chapter_after_the_manual():
    prompt = ta_module._system_prompt_for("", "mobile")
    assert prompt is not None
    assert _chapter_heading() in prompt
    assert prompt.startswith(ta_module.SYSTEM_PROMPT)


def test_persona_override_on_mobile_replaces_everything():
    prompt = ta_module._system_prompt_for("You are a pirate.", "mobile")
    assert prompt == "You are a pirate."


# --- the route actually uses it (a helper nobody calls passes every test above) ---

@pytest.fixture
def app(tmp_path):
    config = {
        "server": {"host": "0.0.0.0", "port": 6969},
        "backends": [
            {"name": "test-backend", "type": "rkllama", "url": "http://localhost:8080", "priority": 1}
        ],
        "qmd": {"url": "http://localhost:7832"},
        "agents": [],
        "metrics": {"poll_interval": 30, "retention_days": 30},
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(config))
    (tmp_path / ".setup_complete").touch()
    return create_app(data_dir=tmp_path)


@pytest_asyncio.fixture
async def client(app):
    ds = app.state.desktop_settings
    if ds._db is not None:
        await ds.close()
    await ds.init()
    app.state.auth.setup_user("admin", "Test Admin", "", "testpass")
    record = app.state.auth.find_user("admin")
    token = app.state.auth.create_session(user_id=record["id"] if record else "", long_lived=True)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"taos_session": token},
        event_hooks=csrf_event_hooks(),
    ) as c:
        yield c
    await ds.close()
    await app.state.http_client.aclose()


async def _system_sent_to_harness(client, app, monkeypatch, device_class: str) -> str | None:
    """Run one opencode chat turn and return the system prompt the adapter got."""
    async def no_problem(app_state, model, prefs):
        return None

    async def fake_ensure_server(state, model):
        return SimpleNamespace(base_url="http://127.0.0.1:4188")

    seen: dict = {}

    class _FakeAdapter:
        def __init__(self, cfg, sink):
            seen["system"] = cfg.system
            self._sink = sink
            self.session_id = None

        async def ensure_session(self):
            self.session_id = "ses_mobile"

        async def prompt(self, text, trace_id=None, attachments=None):
            self._sink({"kind": "final", "content": "ok"})

        async def close(self):
            pass

    monkeypatch.setattr(ta_module, "opencode_gateway_problem", no_problem)
    monkeypatch.setattr(ta_module, "ensure_taos_opencode_server", fake_ensure_server)
    monkeypatch.setattr(ta_module, "OpenCodeAdapter", _FakeAdapter)
    app.state.taos_opencode_password = "testpw"
    app.state.taos_opencode_session_id = None
    app.state.taos_agent_framework_decision = FrameworkDecision(
        "opencode", "opencode", "test", device_class
    )
    await client.patch("/api/taos-agent/settings", json={"model": "gpt-4o"})
    resp = await client.post("/api/taos-agent/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
    assert resp.status_code == 200, resp.text
    assert "system" in seen, "the adapter was never built"
    return seen["system"]


@pytest.mark.asyncio
async def test_chat_route_sends_the_chapter_on_mobile(client, app, monkeypatch):
    system = await _system_sent_to_harness(client, app, monkeypatch, "mobile")
    assert _chapter_heading() in (system or "")


@pytest.mark.asyncio
async def test_chat_route_omits_the_chapter_on_desktop(client, app, monkeypatch):
    system = await _system_sent_to_harness(client, app, monkeypatch, "desktop")
    assert _chapter_heading() not in (system or "")
