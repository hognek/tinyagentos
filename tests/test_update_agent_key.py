"""LiteLLM virtual-key re-scope (update_agent_key) — keystone for synced model management."""
from __future__ import annotations

import pytest
from tinyagentos.llm_proxy import LLMProxy


class _Resp:
    def __init__(self, status): self.status_code = status; self.text = ""

class _Client:
    def __init__(self, status=200, capture=None): self._s = status; self._cap = capture
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json=None, headers=None):
        if self._cap is not None: self._cap["url"] = url; self._cap["json"] = json
        return _Resp(self._s)


class _FakeProxy:
    """Duck-typed proxy borrowing the real update_agent_key implementation."""
    update_agent_key = LLMProxy.update_agent_key
    def __init__(self, running=True, db=True):
        self.url = "http://127.0.0.1:4000"
        self.database_url = "postgres://x" if db else None
        self._running = running
        self._data_dir = None  # in-memory master key (no disk I/O in tests)
    def is_running(self): return self._running


@pytest.mark.asyncio
async def test_update_agent_key_rescopes_in_the_local_store_not_litellm(monkeypatch, tmp_path):
    """Since LiteLLM removal stage 2a the re-scope is the local key store,
    whatever the proxy mode: LiteLLM's /key/update (master key) is never called."""
    from tinyagentos.litellm_keystore import LiteLLMKeyStore, default_keystore_path
    cap = {}
    import tinyagentos.llm_proxy as M
    monkeypatch.setattr(M.httpx, "AsyncClient", lambda **k: _Client(200, cap))
    proxy = LLMProxy(port=4000, data_dir=tmp_path, database_url="postgres://x")
    key = LiteLLMKeyStore(default_keystore_path(tmp_path)).mint("a", ["m"])
    assert await proxy.update_agent_key(key, ["a", "b"]) is True
    assert LiteLLMKeyStore(default_keystore_path(tmp_path)).lookup(key)["allowed_models"] == ["a", "b"]
    assert cap == {}


@pytest.mark.asyncio
async def test_update_agent_key_false_for_a_key_the_store_does_not_hold(tmp_path):
    proxy = LLMProxy(port=4000, data_dir=tmp_path, database_url="postgres://x")
    assert await proxy.update_agent_key("sk-legacy-postgres-key", ["a"]) is False


@pytest.mark.asyncio
async def test_update_agent_key_refuses_empty_models(monkeypatch):
    # An empty scope must NOT silently become ["default"] — refuse and never
    # hit /key/update (which would scope the key to a non-existent model).
    cap = {}
    import tinyagentos.llm_proxy as M
    monkeypatch.setattr(M.httpx, "AsyncClient", lambda **k: _Client(200, cap))
    assert await _FakeProxy().update_agent_key("sk-x", []) is False
    assert cap == {}
