"""Tests for the github_token module — token minting, caching, and
per-agent token lookups."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMintInstallationToken:
    """Tests for mint_installation_token()."""

    @pytest.fixture
    def clean_cache(self):
        """Clear the lifetime cache before each test."""
        import tinyagentos.github_token as gt
        gt._lifetime_cache.clear()
        yield
        gt._lifetime_cache.clear()

    @pytest.mark.asyncio
    async def test_mints_token_via_github_api(self, clean_cache):
        """mint_installation_token() calls the GitHub API and returns a token."""
        from tinyagentos.github_token import mint_installation_token

        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=MagicMock(
            status_code=201,
            json=MagicMock(return_value={
                "token": "ghs_test_token_123",
                "expires_at": "2026-12-31T12:00:00Z",
            }),
            raise_for_status=MagicMock(),
        ))

        with patch("tinyagentos.github_app.generate_jwt", return_value="mock.jwt"):
            token = await mint_installation_token(
                installation_id=42,
                repo="owner/repo",
                app_id="123456",
                private_key="fake-key",
                http_client=http_client,
            )

        assert token == "ghs_test_token_123"
        http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_caches_token_with_lifetime(self, clean_cache):
        """Tokens are cached and returned on subsequent calls."""
        from tinyagentos.github_token import mint_installation_token, _lifetime_cache, _cache_key

        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=MagicMock(
            status_code=201,
            json=MagicMock(return_value={
                "token": "ghs_cached_token",
                "expires_at": "2026-12-31T12:00:00Z",
            }),
            raise_for_status=MagicMock(),
        ))

        with patch("tinyagentos.github_app.generate_jwt", return_value="mock.jwt"):
            token1 = await mint_installation_token(42, "owner/repo", "123456", "fake-key", http_client)
            assert token1 == "ghs_cached_token"
            assert http_client.post.call_count == 1
            assert _cache_key("123456", 42) in _lifetime_cache

            token2 = await mint_installation_token(42, "owner/repo", "123456", "fake-key", http_client)
            assert token2 == "ghs_cached_token"
            assert http_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_none_on_api_failure(self, clean_cache):
        """Returns None when the GitHub API call fails."""
        from tinyagentos.github_token import mint_installation_token

        http_client = AsyncMock()
        http_client.post = AsyncMock(side_effect=Exception("Network error"))

        with patch("tinyagentos.github_app.generate_jwt", return_value="mock.jwt"):
            token = await mint_installation_token(
                installation_id=42,
                repo="owner/repo",
                app_id="123456",
                private_key="fake-key",
                http_client=http_client,
            )

        assert token is None

    @pytest.mark.asyncio
    async def test_refreshes_expired_cache_entry(self, clean_cache):
        """When a cached token is near expiry, a new one is minted."""
        from tinyagentos.github_token import mint_installation_token, _lifetime_cache, _cache_key

        _lifetime_cache[_cache_key("123456", 42)] = ("ghs_old_token", time.time() - 60)

        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=MagicMock(
            status_code=201,
            json=MagicMock(return_value={
                "token": "ghs_new_token",
                "expires_at": "2026-12-31T12:00:00Z",
            }),
            raise_for_status=MagicMock(),
        ))

        with patch("tinyagentos.github_app.generate_jwt", return_value="mock.jwt"):
            token = await mint_installation_token(42, "owner/repo", "123456", "fake-key", http_client)

        assert token == "ghs_new_token"
        assert http_client.post.call_count == 1


class TestGetAgentGitHubToken:
    """Tests for get_agent_github_token()."""

    @pytest.mark.asyncio
    async def test_returns_none_when_app_not_configured(self):
        """Returns None when GitHub App config is missing."""
        from tinyagentos.github_token import get_agent_github_token

        secrets_store = AsyncMock()
        config = MagicMock()
        config.github_app_id = ""
        config.github_app_private_key = ""

        token = await get_agent_github_token(
            "test-agent", secrets_store, config, AsyncMock(),
        )
        assert token is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_installations(self):
        """Returns None when the agent has no github-installation grants."""
        from tinyagentos.github_token import get_agent_github_token

        secrets_store = AsyncMock()
        secrets_store.get_agent_github_installations = AsyncMock(return_value=[])

        config = MagicMock()
        config.github_app_id = "123456"
        config.github_app_private_key = "fake-key"

        token = await get_agent_github_token(
            "test-agent", secrets_store, config, AsyncMock(),
        )
        assert token is None

    @pytest.fixture
    def clean_cache(self):
        import tinyagentos.github_token as gt
        gt._lifetime_cache.clear()
        yield
        gt._lifetime_cache.clear()

    @pytest.mark.asyncio
    async def test_mints_token_for_agent_with_grants(self, clean_cache):
        """Mints a token when the agent has github-installation grants."""
        from tinyagentos.github_token import get_agent_github_token

        secrets_store = AsyncMock()
        secrets_store.get_agent_github_installations = AsyncMock(return_value=[{
            "installation_id": 42,
            "repo_full_name": "owner/repo",
            "permissions": ["contents:read"],
        }])

        config = MagicMock()
        config.github_app_id = "123456"
        config.github_app_private_key = "fake-key"

        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=MagicMock(
            status_code=201,
            json=MagicMock(return_value={
                "token": "ghs_agent_token",
                "expires_at": "2026-12-31T12:00:00Z",
            }),
            raise_for_status=MagicMock(),
        ))

        with patch("tinyagentos.github_app.generate_jwt", return_value="mock.jwt"):
            token = await get_agent_github_token(
                "test-agent", secrets_store, config, http_client,
            )

        assert token == "ghs_agent_token"
        http_client.post.assert_called_once()


class TestAppPrivateKey:
    """The App key moved from config to SecretsStore (#2009)."""

    @pytest.fixture(autouse=True)
    def clean_cache(self):
        import tinyagentos.github_token as gt
        gt._lifetime_cache.clear()
        yield
        gt._lifetime_cache.clear()

    def test_appconfig_no_longer_carries_the_key(self):
        """Why the mocks below are not MagicMock: one would invent the field."""
        import dataclasses

        from tinyagentos.config import AppConfig

        assert "github_app_private_key" not in {f.name for f in dataclasses.fields(AppConfig)}

    @pytest.mark.asyncio
    async def test_mints_with_the_key_from_secrets(self):
        from tinyagentos.github_token import get_agent_github_token

        secrets_store = AsyncMock()
        secrets_store.get = AsyncMock(return_value={"value": "pem-from-secrets"})
        secrets_store.get_agent_github_installations = AsyncMock(
            return_value=[{"installation_id": 42, "repo_full_name": "o/r"}]
        )
        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=MagicMock(
            json=MagicMock(return_value={"token": "ghs_new", "expires_at": "2099-01-01T00:00:00Z"}),
            raise_for_status=MagicMock(),
        ))

        with patch("tinyagentos.github_app.generate_jwt", return_value="jwt") as jwt:
            token = await get_agent_github_token(
                "a", secrets_store, SimpleNamespace(github_app_id="123"), http_client
            )

        assert token == "ghs_new"
        secrets_store.get.assert_awaited_once_with("github-app-private-key")
        jwt.assert_called_once_with("123", "pem-from-secrets")

    @pytest.mark.asyncio
    async def test_no_key_in_secrets_returns_none(self):
        from tinyagentos.github_token import get_agent_github_token

        secrets_store = AsyncMock()
        secrets_store.get = AsyncMock(return_value=None)
        token = await get_agent_github_token(
            "a", secrets_store, SimpleNamespace(github_app_id="123"), AsyncMock()
        )
        assert token is None


class TestFetchAgentTokenState:
    @pytest.mark.asyncio
    async def test_token(self):
        from tinyagentos.github_token import fetch_agent_token_state

        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value="ghs_x")):
            assert await fetch_agent_token_state(
                "a", AsyncMock(), SimpleNamespace(github_app_id="1"), AsyncMock()
            ) == ("ghs_x", True)

    @pytest.mark.asyncio
    async def test_no_grant_is_not_granted(self):
        from tinyagentos.github_token import fetch_agent_token_state

        secrets_store = AsyncMock()
        secrets_store.get_agent_github_installations = AsyncMock(return_value=[])
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value=None)):
            assert await fetch_agent_token_state(
                "a", secrets_store, SimpleNamespace(github_app_id="1"), AsyncMock()
            ) == (None, False)

    @pytest.mark.asyncio
    async def test_failed_mint_with_a_grant_stays_granted(self):
        from tinyagentos.github_token import fetch_agent_token_state

        secrets_store = AsyncMock()
        secrets_store.get_agent_github_installations = AsyncMock(
            return_value=[{"installation_id": 42}]
        )
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value=None)):
            assert await fetch_agent_token_state(
                "a", secrets_store, SimpleNamespace(github_app_id="1"), AsyncMock()
            ) == (None, True)

    @pytest.mark.asyncio
    async def test_exception_degrades_and_stays_granted(self):
        from tinyagentos.github_token import fetch_agent_token_state

        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(side_effect=RuntimeError("boom"))):
            assert await fetch_agent_token_state(
                "a", AsyncMock(), SimpleNamespace(github_app_id="1"), AsyncMock()
            ) == (None, True)


class TestDeployGitHubToken:
    @pytest.mark.asyncio
    async def test_local_deploy_gets_the_token(self):
        from tinyagentos.github_token import deploy_github_token

        state = SimpleNamespace(config=SimpleNamespace(github_app_id="1"), http_client=AsyncMock())
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value="ghs_x")):
            assert await deploy_github_token(state, "a", AsyncMock()) == "ghs_x"

    @pytest.mark.asyncio
    async def test_remote_deploy_gets_none(self):
        from tinyagentos.github_token import deploy_github_token

        state = SimpleNamespace(config=SimpleNamespace(github_app_id="1"), http_client=AsyncMock())
        mint = AsyncMock(return_value="ghs_x")
        with patch("tinyagentos.github_token.get_agent_github_token", mint):
            assert await deploy_github_token(state, "a", AsyncMock(), remote="worker1") == ""
        mint.assert_not_awaited()


def _container(name, status="Running"):
    return SimpleNamespace(name=name, status=status)


class TestRefreshAgentTokens:
    def _state(self, **kwargs):
        secrets_store = AsyncMock()
        secrets_store.get_agent_github_installations = AsyncMock(return_value=[])
        return SimpleNamespace(
            config=SimpleNamespace(github_app_id="1"),
            secrets=secrets_store,
            http_client=AsyncMock(),
            **kwargs,
        )

    @pytest.fixture
    def containers(self):
        with patch("tinyagentos.containers.list_containers", AsyncMock(return_value=[])) as ls, \
             patch("tinyagentos.containers.push_file", AsyncMock(return_value=(0, ""))) as push, \
             patch("tinyagentos.containers.exec_in_container", AsyncMock(return_value=(0, ""))) as ex:
            yield SimpleNamespace(list=ls, push=push, exec=ex)

    @pytest.mark.asyncio
    async def test_rotates_only_servers_that_carry_a_grant(self, containers):
        from tinyagentos.github_token import refresh_agent_tokens

        taos = MagicMock(github_agent="taos-agent")
        other = MagicMock(github_agent=None)
        state = self._state(taos_opencode_servers={"m": taos, "agent-b": other})
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value="ghs_new")):
            await refresh_agent_tokens(state)
        taos.set_github_token.assert_called_once_with("ghs_new")
        other.set_github_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_mint_leaves_the_server_token_alone(self, containers):
        from tinyagentos.github_token import refresh_agent_tokens

        taos = MagicMock(github_agent="taos-agent")
        state = self._state(taos_opencode_servers={"m": taos})
        state.secrets.get_agent_github_installations = AsyncMock(
            return_value=[{"installation_id": 42}]
        )
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value=None)):
            await refresh_agent_tokens(state)
        taos.set_github_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_removed_grant_clears_the_server_token(self, containers):
        from tinyagentos.github_token import refresh_agent_tokens

        taos = MagicMock(github_agent="taos-agent")
        state = self._state(taos_opencode_servers={"m": taos})
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value=None)):
            await refresh_agent_tokens(state)
        taos.set_github_token.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_pushes_a_new_token_once_to_running_containers_only(self, containers):
        from tinyagentos.github_token import CONTAINER_TOKEN_PATH, refresh_agent_tokens

        containers.list.return_value = [
            _container("taos-agent-up"), _container("taos-agent-down", "Stopped"),
        ]
        state = self._state()
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value="ghs_1")) as mint:
            await refresh_agent_tokens(state)
            await refresh_agent_tokens(state)
        assert mint.await_args.args[0] == "up"
        assert containers.push.await_count == 1
        assert containers.push.await_args.args[0] == "taos-agent-up"
        assert containers.push.await_args.args[2] == CONTAINER_TOKEN_PATH
        containers.exec.assert_awaited_once_with(
            "taos-agent-up", ["chmod", "600", CONTAINER_TOKEN_PATH]
        )
        assert state.github_tokens_pushed == {"up": "ghs_1"}

        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value="ghs_2")):
            await refresh_agent_tokens(state)
        assert containers.push.await_count == 2
        assert state.github_tokens_pushed == {"up": "ghs_2"}

    @pytest.mark.asyncio
    async def test_failed_push_is_retried_next_pass(self, containers):
        from tinyagentos.github_token import refresh_agent_tokens

        containers.list.return_value = [_container("taos-agent-up")]
        containers.push.return_value = (1, "offline")
        state = self._state()
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value="ghs_1")):
            await refresh_agent_tokens(state)
            assert state.github_tokens_pushed == {}
            containers.push.return_value = (0, "")
            await refresh_agent_tokens(state)
        assert state.github_tokens_pushed == {"up": "ghs_1"}

    @pytest.mark.asyncio
    async def test_removed_grant_withdraws_the_container_file(self, containers):
        from tinyagentos.github_token import CONTAINER_TOKEN_PATH, refresh_agent_tokens

        containers.list.return_value = [_container("taos-agent-up"), _container("taos-agent-never")]
        state = self._state(github_tokens_pushed={"up": "ghs_old"})
        with patch("tinyagentos.github_token.get_agent_github_token",
                   AsyncMock(return_value=None)):
            await refresh_agent_tokens(state)
        containers.exec.assert_awaited_once_with(
            "taos-agent-up", ["rm", "-f", CONTAINER_TOKEN_PATH]
        )
        assert state.github_tokens_pushed == {}

    @pytest.mark.asyncio
    async def test_no_app_and_nothing_delivered_skips_the_container_listing(self, containers):
        from tinyagentos.github_token import refresh_agent_tokens

        state = self._state()
        state.config.github_app_id = ""
        await refresh_agent_tokens(state)
        containers.list.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_loop_survives_a_failed_pass(self):
        import asyncio

        from tinyagentos.github_token import github_token_refresh_loop

        calls = []

        async def flaky(_state):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")

        with patch("tinyagentos.github_token.refresh_agent_tokens", flaky):
            task = asyncio.create_task(github_token_refresh_loop(SimpleNamespace(), interval=0))
            while len(calls) < 2:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    def test_interval_lands_inside_the_refresh_window(self):
        """A pass must see a token inside the window before it can expire."""
        from tinyagentos.github_token import _REFRESH_WINDOW, REFRESH_INTERVAL_S

        assert REFRESH_INTERVAL_S < _REFRESH_WINDOW
