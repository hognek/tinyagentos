"""LiteLLM removal stage 2a (tsk-ilqzq6): nothing hands out or presents the
LiteLLM master key any more.

Each test measures BEHAVIOUR: which key a deployed agent gets, which key the
taOS agent's opencode gets, whether a screen still answers with LiteLLM
stopped, whether any request reaches LiteLLM with the master key. LiteLLM's
own spawn (config ``master_key`` + ``LITELLM_MASTER_KEY`` env) is the only
reader left, and stage 2b deletes it.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from tinyagentos.litellm_config import get_litellm_master_key
from tinyagentos.litellm_keystore import LiteLLMKeyStore, default_keystore_path

LITELLM_PORT = 4000


def _master(data_dir: Path) -> str:
    return get_litellm_master_key(data_dir)


# ---------------------------------------------------------------------------
# deployer: no scoped key -> a local scoped (gateway-accepted) key, never the master key
# ---------------------------------------------------------------------------


async def _deploy(tmp_path, *, extra=None, remote=False, create_key=None):
    from tinyagentos.deployer import DeployRequest, deploy_agent

    proxy = MagicMock()
    proxy.is_running.return_value = True
    proxy.port = LITELLM_PORT
    proxy.url = f"http://localhost:{LITELLM_PORT}"
    proxy.database_url = None  # routing-only: LiteLLM cannot mint
    proxy._data_dir = tmp_path
    proxy.create_agent_key = create_key or AsyncMock(return_value=None)
    req = DeployRequest(name="fresh", framework="smolagents", model="gpt-a", data_dir=tmp_path,
                        remote=("worker1" if remote else None), taos_host="controller.test",
                        extra_config={"llm_proxy": proxy, **(extra or {})})

    async def mock_exec(name, cmd, **kwargs):
        return (0, "10.0.0.5") if "hostname -I" in " ".join(cmd) else (0, "ok")

    with patch("tinyagentos.deployer.create_container", new_callable=AsyncMock) as mock_create, \
         patch("tinyagentos.deployer.exec_in_container", side_effect=mock_exec), \
         patch("tinyagentos.deployer.push_file", new_callable=AsyncMock, return_value=(0, "")), \
         patch("tinyagentos.deployer.add_proxy_device", new_callable=AsyncMock,
               return_value={"success": True, "output": ""}):
        mock_create.return_value = {"success": True, "name": "taos-agent-fresh"}
        result = await deploy_agent(req)
    env = mock_create.call_args.kwargs["env"] if mock_create.call_args else {}
    return result, env


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_env", [None, "1"], ids=["fallback-env-unset", "fallback-env-set"])
async def test_deploy_without_a_scoped_key_mints_a_local_key_never_the_master_key(
        tmp_path, monkeypatch, fallback_env):
    """LiteLLM could not mint (routing-only) and no gateway port was passed:
    the agent still gets a key scoped to its models, which the gateway
    accepts. TAOS_DISABLE_AGENT_MASTER_KEY_FALLBACK no longer changes anything."""
    from tinyagentos.llm_gateway.auth import gateway_caller

    if fallback_env is None:
        monkeypatch.delenv("TAOS_DISABLE_AGENT_MASTER_KEY_FALLBACK", raising=False)
    else:
        monkeypatch.setenv("TAOS_DISABLE_AGENT_MASTER_KEY_FALLBACK", fallback_env)
    master = _master(tmp_path)
    result, env = await _deploy(tmp_path)
    assert result["success"] is True, result
    key = env["LITELLM_API_KEY"]
    assert key != master and env["OPENAI_API_KEY"] == key
    assert master not in env.values()
    request = SimpleNamespace(state=SimpleNamespace(), headers={"authorization": f"Bearer {key}"},
                              app=SimpleNamespace(state=SimpleNamespace(data_dir=tmp_path)))
    caller = gateway_caller(request)
    assert caller.caller_id == "fresh" and caller.allowed_models == frozenset({"gpt-a", "taos-embedding-default"})


@pytest.mark.asyncio
async def test_deploy_is_refused_when_no_scoped_key_can_be_minted_at_all(tmp_path, monkeypatch):
    monkeypatch.delenv("TAOS_DISABLE_AGENT_MASTER_KEY_FALLBACK", raising=False)
    master = _master(tmp_path)
    with patch("tinyagentos.deployer._mint_local_scoped_key", return_value=None):
        result, env = await _deploy(tmp_path)
    assert result["success"] is False
    assert "master key" in result["error"]
    assert master not in env.values()


@pytest.mark.asyncio
async def test_remote_agent_is_named_as_having_no_gateway_path(tmp_path, caplog):
    """The agent listener is loopback-only: a remote agent has no gateway
    path. The deploy says so by name instead of silently depending on LiteLLM."""
    async def mint(name, models=None):
        return LiteLLMKeyStore(default_keystore_path(tmp_path)).mint(name, models or ["default"])

    with caplog.at_level(logging.WARNING, logger="tinyagentos.deployer"):
        result, env = await _deploy(tmp_path, remote=True, create_key=AsyncMock(side_effect=mint))
    assert result["success"] is True, result
    assert any("llm_gateway_no_remote_path" in r.getMessage() for r in caplog.records)
    assert any("no LLM gateway path" in s for s in result["steps"])


@pytest.mark.asyncio
async def test_cutover_names_the_remote_agent_as_having_no_gateway_path(tmp_path):
    from tinyagentos.llm_gateway import cutover

    report = await cutover.reconcile_agents(
        agents=[{"name": "far", "remote": True, "llm_key": "sk-x"}], data_dir=tmp_path,
        gateway_on=True, gateway_port=7838, litellm_port=LITELLM_PORT, listener_ready=True,
        models_problem=AsyncMock(return_value=None),
    )
    assert report["skipped"][0]["agent"] == "far"
    assert "no LLM gateway path" in report["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_embedding_alias_in_an_allowlist_does_not_bounce_the_agent_back_to_litellm(tmp_path):
    """models_problem reads chat routes only; the embedding alias is served by
    the gateway's /embeddings, so it must not count as unroutable (that would
    move the agent back to LiteLLM on every restart)."""
    from tinyagentos.litellm_config import EMBEDDING_ALIAS
    from tinyagentos.llm_gateway.cutover import models_problem

    state = SimpleNamespace(config=SimpleNamespace(backends=[
        {"name": "c", "type": "openai-compatible", "url": "http://llm.test/v1",
         "models": [{"id": "gpt-a"}], "priority": 1}]), registry=None, desktop_settings=None)
    assert await models_problem(state, ["gpt-a", EMBEDDING_ALIAS]) is None


# ---------------------------------------------------------------------------
# taOS agent runtime: fallback key is scoped, never the master key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taos_agent_falls_back_to_a_scoped_key_not_the_master_key(tmp_path, monkeypatch):
    import tinyagentos.taos_agent_runtime as rt

    master = _master(tmp_path)
    spawned = []

    class _FakeServer:
        def __init__(self, cfg):
            spawned.append(cfg)
            self._cfg = cfg

        async def ensure_running(self, **kwargs):
            pass

        @property
        def base_url(self):
            return f"http://127.0.0.1:{self._cfg.port}"

        def is_running(self):
            return True

    monkeypatch.setattr(rt, "OpenCodeServer", _FakeServer)
    proxy = MagicMock()
    proxy.create_agent_key = AsyncMock(return_value=None)
    proxy.is_running.return_value = False  # LiteLLM stopped
    proxy.port = LITELLM_PORT
    state = SimpleNamespace(data_dir=tmp_path, llm_proxy=proxy, taos_opencode_password=None,
                            taos_opencode_server=None, taos_opencode_model=None,
                            taos_opencode_session_id=None)
    await rt.ensure_taos_opencode_server(state, "gpt-4o")
    key = spawned[0].litellm_key
    assert key and key != master
    rec = LiteLLMKeyStore(default_keystore_path(tmp_path)).lookup(key)
    assert rec == {"agent": "taos-agent", "allowed_models": ["gpt-4o", "taos-embedding-default"]}


# ---------------------------------------------------------------------------
# routes/providers.py: the model catalog no longer asks LiteLLM (with the master key)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("litellm_running", [True, False], ids=["litellm-up", "litellm-stopped"])
async def test_provider_model_catalog_is_read_without_litellm(client, app, litellm_running):
    app.state.config.backends = [
        {"name": "local-llama", "type": "openai-compatible", "url": "http://llm.test:8080/v1",
         "models": [{"id": "qwen3-8b"}, {"id": "gpt-small"}], "priority": 1},
    ]
    proxy = MagicMock()
    proxy.is_running.return_value = litellm_running
    proxy.url = f"http://127.0.0.1:{LITELLM_PORT}"
    proxy.port = LITELLM_PORT
    proxy._data_dir = app.state.data_dir
    app.state.llm_proxy = proxy
    app.state.litellm_models_cache = None
    with respx.mock(assert_all_called=False) as router, \
         patch("tinyagentos.routes.providers._refresh_all_cloud_backends", new=AsyncMock(return_value=0)):
        litellm = router.get(f"http://127.0.0.1:{LITELLM_PORT}/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "from-litellm"}], "object": "list"}))
        resp = await client.post("/api/providers/models/refresh")
    assert resp.status_code == 200, resp.text
    ids = [m["id"] for m in resp.json()["data"]]
    assert {"qwen3-8b", "gpt-small"} <= set(ids)
    assert "from-litellm" not in ids
    assert not litellm.called


# ---------------------------------------------------------------------------
# llm_proxy.py admin calls: the local key store, never LiteLLM's admin API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_key_admin_uses_the_local_store_not_litellm(tmp_path, monkeypatch):
    """Even on a Postgres-configured proxy (inhouse_keys off) mint, re-scope,
    usage and delete never call LiteLLM's /key/* admin API with the master key."""
    from tinyagentos.agent_budget_store import AgentBudgetStore, default_budget_path
    from tinyagentos.llm_proxy import LLMProxy

    proxy = LLMProxy(port=LITELLM_PORT, data_dir=tmp_path, database_url="postgresql://u:p@db/x",
                     inhouse_keys=False)
    monkeypatch.setattr(proxy, "is_running", lambda: True)
    store = LiteLLMKeyStore(default_keystore_path(tmp_path))
    with respx.mock(assert_all_called=False) as router:
        litellm = router.route(host="localhost", port=LITELLM_PORT).mock(
            return_value=httpx.Response(200, json={"key": "sk-from-litellm", "info": {}}))
        key = await proxy.create_agent_key("agent-a", models=["gpt-a"], max_budget=2.5)
        assert key and key != "sk-from-litellm"
        assert store.lookup(key) == {"agent": "agent-a", "allowed_models": ["gpt-a"]}
        assert AgentBudgetStore(default_budget_path(tmp_path)).get("agent-a")["max_budget_usd"] == 2.5
        assert await proxy.update_agent_key(key, ["gpt-b"]) is True
        assert store.lookup(key)["allowed_models"] == ["gpt-b", "taos-embedding-default"]
        usage = await proxy.get_key_usage(key)
        assert usage["info"]["models"] == ["gpt-b", "taos-embedding-default"]
        assert usage["info"]["max_budget"] == 2.5
        assert await proxy.delete_agent_key(key) is True
        assert store.lookup(key) is None
    assert not litellm.called


@pytest.mark.asyncio
async def test_key_usage_screen_answers_with_litellm_stopped(tmp_path, monkeypatch):
    from tinyagentos.llm_proxy import LLMProxy

    proxy = LLMProxy(port=LITELLM_PORT, data_dir=tmp_path, inhouse_keys=True)
    assert proxy.is_running() is False
    key = await proxy.create_agent_key("agent-a", models=["gpt-a"])
    usage = await proxy.get_key_usage(key)
    assert usage is not None and usage["info"]["models"] == ["gpt-a"]


# ---------------------------------------------------------------------------
# litellm_auth.py: the master key is no longer an admin passthrough
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_litellm_auth_hook_no_longer_admits_the_master_key(tmp_path, monkeypatch):
    pytest.importorskip("litellm.proxy._types")
    from fastapi import HTTPException

    import tinyagentos.litellm_auth as auth_mod

    monkeypatch.setattr(auth_mod, "_store", None)
    monkeypatch.setattr(auth_mod, "_store_path", None)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-taos-master-123")
    monkeypatch.setenv("TAOS_LITELLM_KEYSTORE", str(tmp_path / "keys.db"))
    monkeypatch.delenv("TAOS_AGENT_BUDGETS", raising=False)

    class _Req:
        async def json(self):
            return {"model": "gpt-a"}

    with pytest.raises(HTTPException) as exc:
        await auth_mod.user_api_key_auth(_Req(), "sk-taos-master-123")
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# app.py: the reasoning judge never carries the master key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [None, "0"], ids=["gateway-on", "gateway-off"])
async def test_reasoning_judge_never_carries_the_master_key(tmp_data_dir, monkeypatch, flag):
    from tinyagentos.app import create_app
    from tinyagentos.llm_proxy import LLMProxy

    if flag is None:
        monkeypatch.delenv("TAOS_LLM_GATEWAY", raising=False)
    else:
        monkeypatch.setenv("TAOS_LLM_GATEWAY", flag)
    monkeypatch.setattr(LLMProxy, "start", AsyncMock(return_value=False))
    app = create_app(data_dir=tmp_data_dir)
    master = _master(tmp_data_dir)
    async with app.router.lifespan_context(app):
        judge = getattr(app.state.trace_registry, "_judge", None)
        if judge is not None:
            assert judge._api_key != master
            assert judge._api_key == app.state.auth.get_local_token()
            assert judge._base_url.endswith("/api/llm/v1")
        else:
            assert flag == "0"
