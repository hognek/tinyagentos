"""Per-app LLM access: an installed app as its own model-API principal (#613).

Red-first, in the shape the issue asks for: a per-app key restricted to a model
allowlist is REFUSED when it asks for a model outside that list, while the
shared/granted path (the per-install master key / the host local token, which is
what an app has today) still reaches every model.

Both credential surfaces are covered, because both read the same keystore row:

* ``litellm_auth.user_api_key_auth`` -- the hook the LiteLLM proxy (port 7834)
  calls, which is the path an installed app actually hits. Gated on the litellm
  ``proxy`` extra, like the rest of that suite, so it SKIPS on a dev box without
  it; ``TestGatewaySurface`` below is the same rule asserted against a surface
  that needs no extra, so the red-first property is not skipped in CI.
* ``llm_gateway.auth.gateway_caller`` -- the in-process gateway's one auth seam.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import tinyagentos.litellm_auth as hook_mod
import tinyagentos.llm_gateway.auth as gw
from tinyagentos.agent_budget_store import AgentBudgetStore, default_budget_path
from tinyagentos.app_llm_access import (
    DEFAULT_PERMITTED_MODELS,
    base_url,
    env_for,
    inject_install_env,
    manifest_opts_in,
    permitted_models_for_install,
    provision,
    rotate,
    set_access,
)
from tinyagentos.litellm_keystore import (
    KIND_APP,
    LiteLLMKeyStore,
    app_principal,
    default_keystore_path,
)
from tinyagentos.llm_proxy import LLMProxy

APP_ID = "open-webui"


@pytest.fixture(autouse=True)
def _reset_hook_caches(monkeypatch):
    """Isolate the hook module's lazily-cached handles and env between tests."""
    for attr in ("_store", "_store_path", "_budget_store_cache", "_budget_store_cache_path"):
        monkeypatch.setattr(hook_mod, attr, None)
    for var in ("TAOS_LITELLM_KEYSTORE", "TAOS_AGENT_BUDGETS", "LITELLM_MASTER_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield


def _proxy(data_dir) -> LLMProxy:
    """A real in-house-mode proxy (the default for a no-Postgres install)."""
    return LLMProxy(data_dir=data_dir, inhouse_keys=True)


def _store_of(proxy: LLMProxy) -> LiteLLMKeyStore:
    return proxy._keystore()


class _HookReq:
    """The two attributes the hook's scope check reads off a Request."""

    def __init__(self, model):
        self._body = {"model": model}

    async def json(self):
        return self._body


async def _hook_call(token: str, model: str):
    from fastapi import HTTPException
    try:
        return await hook_mod.user_api_key_auth(_HookReq(model), token)
    except ModuleNotFoundError:
        pytest.skip("litellm not installed")
    except HTTPException as exc:
        return exc


class _State:
    pass


class _GatewayReq:
    """The attributes ``gateway_caller`` reads off a starlette Request."""

    def __init__(self, data_dir, token):
        self.app = type("A", (), {"state": _State()})()
        self.app.state.data_dir = data_dir
        self.headers = {"authorization": f"Bearer {token}"}
        self.state = _State()


def _gateway(data_dir, token) -> gw.GatewayCaller:
    return gw.gateway_caller(_GatewayReq(data_dir, token))


# ---------------------------------------------------------------------------
# RED-FIRST: the allowlist refuses, the shared path does not
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_key_outside_its_allowlist_is_refused_by_the_litellm_hook(tmp_path, monkeypatch):
    """The headline case: an app scoped to one model cannot call another."""
    proxy = _proxy(tmp_path)
    token = await proxy.create_app_key(APP_ID, models=["gpt-small"])
    assert token
    monkeypatch.setenv("TAOS_LITELLM_KEYSTORE", str(default_keystore_path(tmp_path)))

    allowed = await _hook_call(token, "gpt-small")
    assert not hasattr(allowed, "status_code"), allowed
    assert allowed.models == ["gpt-small"]
    assert allowed.metadata["principal_kind"] == KIND_APP
    assert allowed.key_alias == f"taos-app-{APP_ID}"

    refused = await _hook_call(token, "qwen3-8b")
    assert refused.status_code == 403, refused
    assert "not permitted for this app" in refused.detail


@pytest.mark.asyncio
async def test_master_key_shared_path_still_reaches_every_model(tmp_path, monkeypatch):
    """The path apps have today keeps working: admin means every model."""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-taos-master-shared-key")
    result = await _hook_call("sk-taos-master-shared-key", "any-model-at-all")
    assert not hasattr(result, "status_code"), result


class TestGatewaySurface:
    """Same rule, on a surface that needs no litellm extra (runs in CI)."""

    def test_app_caller_gets_the_app_kind_and_its_exact_allowlist(self, tmp_path):
        token = _store_of(_proxy(tmp_path)).mint(
            app_principal(APP_ID), ["gpt-small"], kind=KIND_APP
        )
        caller = _gateway(tmp_path, token)
        assert caller.kind == KIND_APP
        assert caller.caller_id == app_principal(APP_ID)
        assert caller.may_use("gpt-small") is True
        assert caller.may_use("qwen3-8b") is False
        assert caller.may_use("taos-default") is False

    def test_agent_caller_is_unaffected(self, tmp_path):
        """The same store still yields kind 'agent' for an agent row."""
        token = _store_of(_proxy(tmp_path)).mint("agent-a", ["gpt-small"])
        caller = _gateway(tmp_path, token)
        assert (caller.caller_id, caller.kind) == ("agent-a", "agent")

    def test_host_local_token_is_still_every_model(self, tmp_path):
        """The shared path (what an app has today) is unchanged: admin, all models."""
        (tmp_path / ".auth_local_token").write_text("sk-taos-host-local-token-abcdef")
        caller = _gateway(tmp_path, "sk-taos-host-local-token-abcdef")
        assert caller.kind == "local_token"
        assert caller.allowed_models is None
        assert all(caller.may_use(m) for m in ("gpt-small", "qwen3-8b", "whatever"))

    def test_app_principal_is_not_subject_to_the_agent_budget(self, tmp_path):
        """An app is not an agent: an over-budget AGENT is refused, an over-budget
        APP is not, because app budgets are not a thing."""
        budget_path = default_budget_path(tmp_path)
        budgets = AgentBudgetStore(budget_path)
        budgets.set_budget("agent-broke", 1.0)
        budgets.add_spend("agent-broke", 5.0)
        budgets.set_budget(app_principal(APP_ID), 1.0)
        budgets.add_spend(app_principal(APP_ID), 5.0)

        store = _store_of(_proxy(tmp_path))
        agent_token = store.mint("agent-broke", ["gpt-small"])
        app_token = store.mint(app_principal(APP_ID), ["gpt-small"], kind=KIND_APP)

        with pytest.raises(gw.BudgetExceeded):
            _gateway(tmp_path, agent_token)
        app_caller = _gateway(tmp_path, app_token)
        assert (app_caller.kind, app_caller.may_use("gpt-small")) == (KIND_APP, True)

    def test_empty_allowlist_app_key_may_use_nothing(self, tmp_path):
        token = _store_of(_proxy(tmp_path)).mint(
            app_principal(APP_ID), [], kind=KIND_APP
        )
        caller = _gateway(tmp_path, token)
        assert caller.kind == KIND_APP
        for model in ("default", "taos-default", "gpt-small"):
            assert caller.may_use(model) is False


def test_scope_refusal_names_the_app_not_the_agent():
    """The refusal text distinguishes the two principals (no copy-paste drift)."""
    assert hook_mod.model_scope_error(KIND_APP, ["a"], "b") == (
        "model 'b' is not permitted for this app"
    )
    assert hook_mod.model_scope_error("agent", ["a"], "b") == (
        "model 'b' is not permitted for this agent"
    )
    assert hook_mod.model_scope_error(KIND_APP, [], None) == (
        "no models are permitted for this app"
    )
    assert hook_mod.model_scope_error(KIND_APP, ["a"], "a") is None


# ---------------------------------------------------------------------------
# Principal identity: the app is a first-class principal, not an agent alias
# ---------------------------------------------------------------------------


class TestPrincipalValidation:
    def test_app_principal_prefix(self):
        assert app_principal(APP_ID) == f"app:{APP_ID}"
        assert app_principal(f"app:{APP_ID}") == f"app:{APP_ID}"

    def test_kind_and_name_must_agree(self, tmp_path):
        store = _store_of(_proxy(tmp_path))
        with pytest.raises(ValueError):
            store.mint(APP_ID, ["default"], kind=KIND_APP)  # bare name as an app
        with pytest.raises(ValueError):
            store.mint(app_principal(APP_ID), ["default"])  # app name as an agent
        with pytest.raises(ValueError):
            store.mint("app:", ["default"], kind=KIND_APP)  # empty app id
        with pytest.raises(ValueError):
            store.mint(APP_ID, ["default"], kind="node")  # unknown kind

    def test_keys_for_principal_reports_kind_and_scope(self, tmp_path):
        store = _store_of(_proxy(tmp_path))
        token = store.mint(app_principal(APP_ID), ["gpt-small"], kind=KIND_APP)
        (row,) = store.keys_for_principal(app_principal(APP_ID))
        assert (row["token"], row["kind"], row["allowed_models"]) == (
            token, KIND_APP, ["gpt-small"],
        )
        assert store.lookup(token)["kind"] == KIND_APP
        assert store.keys_for_principal(f"app:absent") == []


# ---------------------------------------------------------------------------
# Proxy-side lifecycle: mint, read, re-scope in place, drop
# ---------------------------------------------------------------------------


class TestProxyLifecycle:
    @pytest.mark.asyncio
    async def test_mint_read_rescope_delete(self, tmp_path):
        proxy = _proxy(tmp_path)
        token = await proxy.create_app_key(APP_ID, models=["gpt-small"])
        assert token and token.startswith("sk-taos-")

        state = proxy.app_key_state(APP_ID)
        assert state == {"key": token, "allowed_models": ["gpt-small"]}

        # Re-scoping must NOT change the key value: a running container keeps
        # working with the credential it was handed.
        assert await proxy.set_app_models(APP_ID, ["gpt-small", "qwen3-8b"]) is True
        rescoped = proxy.app_key_state(APP_ID)
        assert rescoped["key"] == token
        assert rescoped["allowed_models"] == ["gpt-small", "qwen3-8b"]

        assert await proxy.delete_app_key(APP_ID) is True
        assert proxy.app_key_state(APP_ID) is None

    @pytest.mark.asyncio
    async def test_default_scope_is_the_usable_chat_alias(self, tmp_path):
        proxy = _proxy(tmp_path)
        await proxy.create_app_key(APP_ID)
        assert proxy.app_key_state(APP_ID)["allowed_models"] == list(DEFAULT_PERMITTED_MODELS)

    @pytest.mark.asyncio
    async def test_empty_scope_is_refused_not_silently_allow_all(self, tmp_path):
        proxy = _proxy(tmp_path)
        await proxy.create_app_key(APP_ID, models=["gpt-small"])
        assert await proxy.set_app_models(APP_ID, []) is False
        assert proxy.app_key_state(APP_ID)["allowed_models"] == ["gpt-small"]

    @pytest.mark.asyncio
    async def test_routing_only_mode_mints_nothing(self, tmp_path):
        """No in-house keys and no Postgres: no key, and the caller is told so
        rather than handed an empty credential."""
        proxy = LLMProxy(data_dir=tmp_path, inhouse_keys=False)
        assert await proxy.create_app_key(APP_ID, models=["gpt-small"]) is None
        assert proxy.app_key_state(APP_ID) is None
        assert await proxy.set_app_models(APP_ID, ["gpt-small"]) is False

    @pytest.mark.asyncio
    async def test_two_apps_get_two_distinct_keys(self, tmp_path):
        proxy = _proxy(tmp_path)
        a = await proxy.create_app_key("open-webui", models=["gpt-small"])
        b = await proxy.create_app_key("librechat", models=["qwen3-8b"])
        assert a != b
        assert proxy.app_key_state("open-webui")["key"] == a
        assert proxy.app_key_state("librechat")["key"] == b
        assert await proxy.set_app_models("open-webui", ["gpt-small"]) is True
        # Re-scoping one app must not touch the other's scope.
        assert proxy.app_key_state("librechat")["allowed_models"] == ["qwen3-8b"]


# ---------------------------------------------------------------------------
# app_llm_access: the orchestration layer
# ---------------------------------------------------------------------------


class _Manifest:
    def __init__(self, install):
        self.install = install


class TestManifestOptIn:
    def test_opts_in_only_on_an_explicit_true(self):
        assert manifest_opts_in(_Manifest({"llm_access": True})) is True
        assert manifest_opts_in(_Manifest({"llm_access": False})) is False
        assert manifest_opts_in(_Manifest({})) is False
        assert manifest_opts_in(_Manifest(None)) is False
        assert manifest_opts_in(None) is False
        assert manifest_opts_in(_Manifest("not-a-mapping")) is False

    def test_default_scope_and_a_declared_one(self):
        assert permitted_models_for_install(_Manifest({})) == list(DEFAULT_PERMITTED_MODELS)
        assert permitted_models_for_install(
            _Manifest({"llm_models": ["a", "b"]})
        ) == ["a", "b"]
        assert permitted_models_for_install(_Manifest({"llm_models": "a"})) == ["a"]
        assert permitted_models_for_install(
            _Manifest({"llm_models": ["", "  ", 7]})
        ) == list(DEFAULT_PERMITTED_MODELS)

    def test_the_catalog_reference_app_opts_in(self):
        """open-webui is the documented example: keep it wired, and prove the
        field survives manifest parsing (not just the raw YAML)."""
        import yaml

        from tinyagentos.registry import AppManifest

        catalog = Path(__file__).resolve().parent.parent / "app-catalog"
        raw = yaml.safe_load(
            (catalog / "services" / "open-webui" / "manifest.yaml").read_text()
        )
        manifest = AppManifest.from_dict(raw, manifest_dir=catalog)
        assert manifest_opts_in(manifest) is True
        assert permitted_models_for_install(manifest) == list(DEFAULT_PERMITTED_MODELS)


class _FakeProxy:
    """Records what install asked for, without a keystore."""

    def __init__(self, token="sk-taos-app-token", port=7834):
        self.port = port
        self.created: list[tuple[str, object]] = []
        self.rescoped: list[tuple[str, list[str]]] = []
        self._state: dict[str, dict] = {}
        self._token = token

    def app_key_state(self, app_id):
        return self._state.get(app_id)

    async def create_app_key(self, app_id, models=None):
        self.created.append((app_id, models))
        self._state[app_id] = {
            "key": self._token,
            "allowed_models": list(models or DEFAULT_PERMITTED_MODELS),
        }
        return self._token

    async def set_app_models(self, app_id, models):
        self.rescoped.append((app_id, list(models)))
        if app_id not in self._state:
            return False
        self._state[app_id]["allowed_models"] = list(models)
        return True

    async def delete_app_key(self, app_id):
        return self._state.pop(app_id, None) is not None


class _InstallReq:
    def __init__(self, proxy):
        self.app = type("A", (), {"state": _State()})()
        self.app.state.llm_proxy = proxy


class TestInstallInjection:
    @pytest.mark.asyncio
    async def test_env_is_merged_for_an_opting_in_app(self):
        proxy = _FakeProxy()
        config = {"method": "docker", "env": {"OLLAMA_BASE_URL": "http://host:11434"}}
        token = await inject_install_env(
            _InstallReq(proxy), APP_ID, config, _Manifest({"llm_access": True})
        )
        assert token == proxy._token
        assert config["env"]["OPENAI_API_KEY"] == token
        assert config["env"]["LITELLM_API_KEY"] == token
        assert config["env"]["OPENAI_BASE_URL"] == base_url(7834)
        assert config["env"]["OPENAI_BASE_URL"] == "http://host.docker.internal:7834/v1"
        # The manifest's own env survives.
        assert config["env"]["OLLAMA_BASE_URL"] == "http://host:11434"

    @pytest.mark.asyncio
    async def test_a_manifest_pinned_env_value_is_not_clobbered(self):
        proxy = _FakeProxy()
        config = {"env": {"OPENAI_BASE_URL": "https://api.example.com/v1"}}
        await inject_install_env(
            _InstallReq(proxy), APP_ID, config, _Manifest({"llm_access": True})
        )
        assert config["env"]["OPENAI_BASE_URL"] == "https://api.example.com/v1"
        assert config["env"]["OPENAI_API_KEY"] == proxy._token

    @pytest.mark.asyncio
    async def test_a_manifest_that_never_opts_in_mints_nothing(self):
        proxy = _FakeProxy()
        config: dict = {}
        assert await inject_install_env(_InstallReq(proxy), APP_ID, config, _Manifest({})) is None
        assert proxy.created == []
        assert config == {}

    @pytest.mark.asyncio
    async def test_no_proxy_means_no_credential_but_no_crash(self):
        config: dict = {}
        assert await inject_install_env(
            _InstallReq(None), APP_ID, config, _Manifest({"llm_access": True})
        ) is None
        assert config == {}

    @pytest.mark.asyncio
    async def test_a_manifest_declared_scope_is_used(self):
        proxy = _FakeProxy()
        await inject_install_env(
            _InstallReq(proxy), APP_ID, {},
            _Manifest({"llm_access": True, "llm_models": ["gpt-small", "qwen3-8b"]}),
        )
        assert proxy.created == [(APP_ID, ["gpt-small", "qwen3-8b"])]

    def test_env_shape(self):
        assert env_for("tok", "http://h:1/v1") == {
            "OPENAI_BASE_URL": "http://h:1/v1",
            "OPENAI_API_KEY": "tok",
            "LITELLM_API_KEY": "tok",
        }
        assert base_url(7834) == "http://host.docker.internal:7834/v1"
        assert base_url(4000) == "http://host.docker.internal:4000/v1"


class TestOrchestration:
    @pytest.mark.asyncio
    async def test_provision_reuses_the_key_and_rescopes_it(self, tmp_path):
        proxy = _proxy(tmp_path)
        first = await provision(proxy, APP_ID, models=["gpt-small"])
        second = await provision(proxy, APP_ID, models=["qwen3-8b"])
        # Same key value: a reinstall does not invalidate a running container.
        assert first == second
        assert proxy.app_key_state(APP_ID)["allowed_models"] == ["qwen3-8b"]
        assert len(_store_of(proxy).keys_for_principal(app_principal(APP_ID))) == 1

    @pytest.mark.asyncio
    async def test_set_access_reports_what_it_did(self, tmp_path):
        proxy = _proxy(tmp_path)
        assert (await set_access(proxy, APP_ID, ["gpt-small"]))["key_action"] == "minted"
        assert (await set_access(proxy, APP_ID, ["gpt-small"]))["key_action"] == "unchanged"
        rescoped = await set_access(proxy, APP_ID, ["qwen3-8b"])
        assert rescoped["key_action"] == "rescoped"
        assert rescoped["permitted_models"] == ["qwen3-8b"]
        assert (await set_access(None, APP_ID, ["x"]))["key_action"] == "none"

    @pytest.mark.asyncio
    async def test_rotate_replaces_the_key_and_keeps_the_scope(self, tmp_path):
        proxy = _proxy(tmp_path)
        old = await provision(proxy, APP_ID, models=["gpt-small"])
        new = await rotate(proxy, APP_ID)
        assert new and new != old
        assert proxy.app_key_state(APP_ID)["key"] == new
        assert proxy.app_key_state(APP_ID)["allowed_models"] == ["gpt-small"]
        # The rotated-out key is gone, not merely superseded.
        assert len(_store_of(proxy).keys_for_principal(app_principal(APP_ID))) == 1


# ---------------------------------------------------------------------------
# Route surface: the app's own settings
# ---------------------------------------------------------------------------


def app_key_state_of(client, app_id: str) -> str:
    """The app's live plaintext key, read straight off the app's own proxy.

    Test-only: the route deliberately never returns it, so the mask assertion
    needs a second source of truth rather than the response under test.
    """
    proxy = client._transport.app.state.llm_proxy
    return (proxy.app_key_state(app_id) or {}).get("key") or ""


class TestAccessStateTriState:
    """``key_present`` must not lie: false, true, or genuinely unknown."""

    class _Pg:
        inhouse_keys = False
        database_url = "postgresql://x"

        def app_key_state(self, app_id):
            return None

    @pytest.mark.asyncio
    async def test_unknown_only_when_the_store_is_out_of_reach(self):
        from tinyagentos.app_llm_access import access_state

        assert (await access_state(None, APP_ID))["key_present"] is False
        assert (await access_state(self._Pg(), APP_ID))["key_present"] is None

        class _Routing:
            inhouse_keys = False
            database_url = None

            def app_key_state(self, app_id):
                return None

        assert (await access_state(_Routing(), APP_ID))["key_present"] is False


@pytest.mark.asyncio
async def test_get_llm_access_reports_state(client):
    resp = await client.get(f"/api/apps/{APP_ID}/llm-access")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["app_id"] == APP_ID
    assert body["permitted_models"] == []
    assert body["key_present"] is False
    assert body["key_masked"] is None
    # The reference catalog app declares the opt-in, and the route reads the
    # same manifest field install does.
    assert body["declares_llm_access"] is True


@pytest.mark.asyncio
async def test_put_then_get_round_trip(client):
    resp = await client.put(
        f"/api/apps/{APP_ID}/llm-access", json={"models": ["gpt-small", "qwen3-8b"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["key_action"] == "minted"

    body = (await client.get(f"/api/apps/{APP_ID}/llm-access")).json()
    assert body["permitted_models"] == ["gpt-small", "qwen3-8b"]
    assert body["key_present"] is True
    # The masked value recognises a key without handing one out.
    assert body["key_masked"].startswith("sk-taos-")
    live = app_key_state_of(client, APP_ID)
    assert live not in body["key_masked"]

    # A second PUT re-scopes in place rather than minting again.
    again = await client.put(f"/api/apps/{APP_ID}/llm-access", json={"models": ["gpt-small"]})
    assert again.status_code == 200, again.text
    assert again.json()["key_action"] == "rescoped"


@pytest.mark.asyncio
async def test_put_with_no_models_is_refused(client):
    resp = await client.put(f"/api/apps/{APP_ID}/llm-access", json={"models": []})
    assert resp.status_code == 400, resp.text
    assert "must not be empty" in resp.json()["error"]


@pytest.mark.asyncio
async def test_rotate_returns_the_plaintext_once(client):
    await client.put(f"/api/apps/{APP_ID}/llm-access", json={"models": ["gpt-small"]})
    resp = await client.post(f"/api/apps/{APP_ID}/llm-access/rotate")
    assert resp.status_code == 200, resp.text
    token = resp.json()["key"]
    assert token.startswith("sk-taos-")
    # The rotated key is the live one, and the route never echoes it back again.
    assert (await client.get(f"/api/apps/{APP_ID}/llm-access")).json()["key_masked"] == (
        f"sk-taos-…{token[-4:]}"
    )


@pytest.mark.asyncio
async def test_llm_access_writes_require_a_session(client):
    """No session cookie at all: 401/403, never a mint."""
    from httpx import ASGITransport, AsyncClient

    app = client._transport.app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        for method, path in (
            ("put", f"/api/apps/{APP_ID}/llm-access"),
            ("post", f"/api/apps/{APP_ID}/llm-access/rotate"),
        ):
            call = getattr(anon, method)
            resp = await call(path, json={"models": ["gpt-small"]})
            assert resp.status_code in (401, 403), (method, resp.status_code, resp.text)
