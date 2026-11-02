"""GitHub App installation token minting + per-agent cache.

Layered on top of ``tinyagentos.github_app`` which handles JWT generation
and the raw ``POST /app/installations/{id}/access_tokens`` call. This
module adds:

- Lifetime-aware caching: tokens are cached until 5 min before expiry
  (GitHub issues tokens valid for 1 hour).
- Per-agent lookups: ``get_agent_github_token(agent_name)`` queries the
  SecretsStore for ``github-installation`` secrets the agent is granted,
  mints a token scoped to those repos, and returns it.
- Delivery: ``refresh_agent_tokens`` keeps every granted agent's token current,
  and ``github_token_refresh_loop`` runs it for the life of the controller.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
    from tinyagentos.config import AppConfig
    from tinyagentos.secrets import SecretsStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifetime-aware token cache
# ---------------------------------------------------------------------------

# key = "app_id:installation_id" -> (token, expiry_unix_timestamp)
_lifetime_cache: dict[str, tuple[str, float]] = {}
_MAX_CACHE_SIZE = 100
_REFRESH_WINDOW = 300  # Refresh when < 5 min remain (token lifetime is 1 hour)

# Shorter than _REFRESH_WINDOW, so a pass always lands inside the window and the
# delivered token is replaced before it expires.
REFRESH_INTERVAL_S = 240

# The App's private key lives in the encrypted SecretsStore, not in config.
APP_KEY_SECRET = "github-app-private-key"
# Inside an agent container. Frameworks run as root (see the SSH key step in
# deployer.py). The agent manual re-exports from this file before using git/gh.
CONTAINER_TOKEN_PATH = "/root/.taos-github-token"


def _cache_key(app_id: str, installation_id: int) -> str:
    return f"{app_id}:{installation_id}"


def _evict_if_full() -> None:
    if len(_lifetime_cache) >= _MAX_CACHE_SIZE:
        # Evict the entry with the oldest expiry timestamp (LRU by deadline)
        oldest_key = min(_lifetime_cache, key=lambda k: _lifetime_cache[k][1])
        del _lifetime_cache[oldest_key]


def _cached_token_lifetime(key: str) -> str | None:
    """Return a cached token if it still has > 5 min of life."""
    entry = _lifetime_cache.get(key)
    if entry:
        token, expiry = entry
        if time.time() < expiry - _REFRESH_WINDOW:
            return token
        del _lifetime_cache[key]
    return None


async def mint_installation_token(
    installation_id: int,
    repo: str,
    app_id: str,
    private_key: str,
    http_client: httpx.AsyncClient,
) -> str | None:
    """Mint a short-lived GitHub App installation token.

    The token is scoped to all repos the installation has access to.
    The *repo* parameter is accepted for future per-repo scoping but
    is not currently enforced by the GitHub API.

    Results are cached with lifetime awareness — the cache tracks the
    actual ``expires_at`` from GitHub and auto-refreshes when fewer
    than 5 minutes remain.
    """
    key = _cache_key(app_id, installation_id)
    cached = _cached_token_lifetime(key)
    if cached:
        return cached

    from tinyagentos.github_app import generate_jwt, _auth_headers, _INSTALL_TOKEN_URL

    try:
        jwt = generate_jwt(app_id, private_key)
        url = _INSTALL_TOKEN_URL.format(installation_id=installation_id)
        # Optionally scope to a single repo via the repository_ids parameter.
        # The standard flow mints a token valid for all repos the installation
        # can see; we don't currently resolve repo -> repo_id, so skip for now.
        resp = await http_client.post(
            url,
            headers=_auth_headers(jwt),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token")
        if token:
            # GitHub returns an expires_at ISO-8601 string (e.g.,
            # "2025-01-01T12:00:00Z"). Parse it out so we track
            # real lifetime rather than a fixed TTL.
            expires_str = data.get("expires_at", "")
            if expires_str:
                try:
                    from datetime import datetime, timezone as dt_timezone
                    expires_dt = datetime.fromisoformat(
                        expires_str.replace("Z", "+00:00")
                    )
                    expires_ts = expires_dt.timestamp()
                except (ValueError, TypeError):
                    expires_ts = time.time() + 3600  # fallback: 1 hour
            else:
                expires_ts = time.time() + 3600

            _evict_if_full()
            _lifetime_cache[key] = (token, expires_ts)
        return token
    except Exception as exc:
        logger.exception(
            "Failed to mint installation token for installation %s: %s",
            installation_id,
            exc,
        )
        return None


async def _app_private_key(secrets_store: SecretsStore) -> str | None:
    rec = await secrets_store.get(APP_KEY_SECRET)
    return (rec.get("value") or None) if rec else None


async def get_agent_github_token(
    agent_name: str,
    secrets_store: SecretsStore,
    config: AppConfig,
    http_client: httpx.AsyncClient,
) -> str | None:
    """Return a short-lived GitHub token for *agent_name*, or None.

    Looks up all ``github-installation`` secrets the agent is granted
    access to via ``SecretsStore.get_agent_github_installations()`` and
    tries each installation in turn until a token is successfully minted.

    The minted token is scoped to the **entire** installation (all repos
    the installation can access), not to individual repos.  Per-repo
    grants in the UI reflect which agents can *request* a token; the
    backend does not currently enforce per-repo token scoping via GitHub's
    ``repository_ids`` parameter — that is tracked as a future enhancement.

    Returns None if the agent has no GitHub App access grants, the
    GitHub App is not configured, or token minting fails for all
    installations.
    """
    if not config.github_app_id:
        return None
    private_key = await _app_private_key(secrets_store)
    if not private_key:
        return None

    installations = await secrets_store.get_agent_github_installations(agent_name)
    if not installations:
        return None

    # Try each granted installation until we mint a valid token.
    for inst in installations:
        iid = inst.get("installation_id")
        repo = inst.get("repo_full_name", "")

        if not iid:
            continue

        token = await mint_installation_token(
            installation_id=iid,
            repo=repo,
            app_id=config.github_app_id,
            private_key=private_key,
            http_client=http_client,
        )
        if token:
            return token

    return None


async def fetch_agent_token_state(
    agent_name: str,
    secrets_store: SecretsStore,
    config: AppConfig,
    http_client: httpx.AsyncClient,
) -> tuple[str | None, bool]:
    """Return ``(token, granted)`` for *agent_name*. Never raises.

    The two ``None`` cases need different handling, so ``granted`` separates
    them. ``(None, False)``: the agent has no grant, so a delivered token must
    be withdrawn. ``(None, True)``: minting failed or could not be checked, so a
    delivered token may still be valid and must be left alone.
    """
    try:
        token = await get_agent_github_token(
            agent_name, secrets_store, config, http_client
        )
    except Exception:  # noqa: BLE001 - degrade, never break agent startup
        logger.exception("Could not fetch GitHub token for agent %s", agent_name)
        return None, True
    if token:
        return token, True
    if not config.github_app_id:
        return None, False
    try:
        return None, bool(await secrets_store.get_agent_github_installations(agent_name))
    except Exception:  # noqa: BLE001 - unknown is not the same as revoked
        logger.exception("Could not read GitHub grants for agent %s", agent_name)
        return None, True


async def deploy_github_token(
    app_state, agent_name: str, secrets_store: SecretsStore | None, remote: str | None = None
) -> str:
    """The token to deploy *agent_name* with, or ``""`` if it gets none.

    A remote agent gets none: the refresh loop only reaches local containers, so
    its token would expire an hour after deploy with nothing to replace it.
    """
    config = getattr(app_state, "config", None)
    http_client = getattr(app_state, "http_client", None)
    if remote or secrets_store is None or config is None or http_client is None:
        return ""
    token, _granted = await fetch_agent_token_state(
        agent_name, secrets_store, config, http_client
    )
    return token or ""


async def push_token_file(container: str, token: str) -> bool:
    """Write *token* to the agent container's 0600 credential file."""
    from tinyagentos import containers

    fd, tmp_path = tempfile.mkstemp(suffix=".token")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token + "\n")
        rc, output = await containers.push_file(container, tmp_path, CONTAINER_TOKEN_PATH)
    finally:
        os.unlink(tmp_path)
    if rc != 0:
        logger.warning("Could not push GitHub token to %s (rc=%s)", container, rc)
        return False
    rc, output = await containers.exec_in_container(
        container, ["chmod", "600", CONTAINER_TOKEN_PATH]
    )
    if rc != 0:
        logger.warning("Could not chmod GitHub token in %s: %s", container, output[-200:])
        return False
    return True


async def _remove_token_file(container: str) -> bool:
    from tinyagentos import containers

    rc, output = await containers.exec_in_container(
        container, ["rm", "-f", CONTAINER_TOKEN_PATH]
    )
    if rc != 0:
        logger.warning("Could not remove GitHub token from %s: %s", container, output[-200:])
    return rc == 0


async def refresh_agent_tokens(app_state) -> None:
    """Rotate the GitHub token of every agent that has one, once.

    Covers the taOS agent's opencode servers and running local agent containers.
    A container's process env cannot change after start, so its credential file
    is the rotation channel. A removed grant withdraws the file; the token itself
    stays valid at GitHub until it expires, at most an hour later.
    """
    config = getattr(app_state, "config", None)
    secrets_store = getattr(app_state, "secrets", None)
    http_client = getattr(app_state, "http_client", None)
    if config is None or secrets_store is None or http_client is None:
        return

    pushed: dict[str, str] = getattr(app_state, "github_tokens_pushed", None) or {}
    app_state.github_tokens_pushed = pushed
    servers = getattr(app_state, "taos_opencode_servers", None) or {}

    for server in list(servers.values()):
        agent_name = getattr(server, "github_agent", None)
        if not agent_name:
            continue
        token, granted = await fetch_agent_token_state(
            agent_name, secrets_store, config, http_client
        )
        if token or not granted:
            server.set_github_token(token)

    # Nothing can be minted and nothing was delivered: skip the container listing.
    if not config.github_app_id and not pushed:
        return

    from tinyagentos import containers

    prefix = "taos-agent-"
    for info in await containers.list_containers(prefix):
        if info.status.lower() != "running":
            continue
        agent_name = info.name.removeprefix(prefix)
        token, granted = await fetch_agent_token_state(
            agent_name, secrets_store, config, http_client
        )
        if token:
            if pushed.get(agent_name) != token and await push_token_file(info.name, token):
                pushed[agent_name] = token
        elif not granted and agent_name in pushed:
            if await _remove_token_file(info.name):
                del pushed[agent_name]


async def github_token_refresh_loop(app_state, interval: float = REFRESH_INTERVAL_S) -> None:
    """Run :func:`refresh_agent_tokens` until cancelled."""
    while True:
        await asyncio.sleep(interval)
        try:
            await refresh_agent_tokens(app_state)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the next pass retries
            logger.exception("GitHub token refresh pass failed")
