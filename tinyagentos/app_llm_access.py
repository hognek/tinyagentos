"""Per-app LLM access: an installed app's own key + model allowlist (#613).

An installed app that talks to the model API (open-webui, LibreChat,
Perplexica, AnythingLLM, ...) gets its own LiteLLM principal instead of the one
shared master key every app would otherwise have to be handed:

- on install, a key is minted bound to ``app:<app_id>`` with a model
  allowlist, and injected into the app's container env as ``OPENAI_BASE_URL`` /
  ``OPENAI_API_KEY``. Opting in is declarative: ``install.llm_access: true`` in
  the manifest (see ``app-catalog/services/open-webui/manifest.yaml``).
- the allowlist is enforced on BOTH credential surfaces, because both read the
  same row: the LiteLLM ``custom_auth`` hook
  (``tinyagentos.litellm_auth``) and the in-process LLM gateway
  (``tinyagentos.llm_gateway.auth``, kind ``app``).
- the operator reads and re-scopes it through
  ``GET/PUT /api/apps/{app_id}/llm-access`` (``routes/app_permissions.py``).
  A re-scope keeps the key VALUE, so a running container needs no restart.

Everything here is best-effort at install time: an install that cannot mint
(proxy disabled, routing-only mode, no Postgres) still installs, it just gets no
model credential, and the reason is logged rather than swallowing the install.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# What an OpenAI-compatible app reads. OPENAI_API_KEY is the near-universal
# name; LITELLM_API_KEY is the one the taOS agent deployer also sets, so an app
# wired against that convention works unchanged.
ENV_BASE_URL = "OPENAI_BASE_URL"
ENV_API_KEY = "OPENAI_API_KEY"
ENV_LITELLM_KEY = "LITELLM_API_KEY"

# Host a docker container uses to reach the taOS controller. The catalog's own
# model-consuming manifests already use this name for OLLAMA_BASE_URL, and
# DockerInstaller writes the matching extra_hosts entry for any env value that
# references it (so the alias resolves on Linux too, not just Docker Desktop).
DOCKER_HOST_ALIAS = "host.docker.internal"

# The scope an opting-in app is minted with when its manifest names no set: the
# ``default`` chat alias generate_litellm_config always emits. A usable
# single-model scope rather than a deny-all key.
DEFAULT_PERMITTED_MODELS = ("default",)

# The manifest key that opts an app into a per-app principal.
LLM_ACCESS_KEY = "llm_access"
# Optional manifest key naming the models the app may use.
LLM_MODELS_KEY = "llm_models"


def base_url(port: int) -> str:
    """The OpenAI-compatible base URL a dockerised app should talk to.

    ``host.docker.internal`` and not ``127.0.0.1``: inside the app's container,
    loopback is the app, and the proxy listens on the host. (The deployer uses
    ``127.0.0.1`` for LXC agents, which reach the host through a proxy device —
    a container has no equivalent.)
    """
    return f"http://{DOCKER_HOST_ALIAS}:{port}/v1"


def env_for(token: str, url: str) -> dict[str, str]:
    """The env an app needs to use its own principal's key."""
    return {ENV_BASE_URL: url, ENV_API_KEY: token, ENV_LITELLM_KEY: token}


def _install_block(manifest) -> dict:
    install = getattr(manifest, "install", None) or {}
    return install if isinstance(install, dict) else {}


def manifest_opts_in(manifest) -> bool:
    """True when a manifest declares that the app calls the model API.

    ``install.llm_access: true``. Explicit rather than implicit so taOS does not
    mint a model credential for every installed service — gitea, ddns,
    uptime-kuma and friends never call the LLM, and an unused key is an unused
    key to revoke.
    """
    if manifest is None:
        return False
    return bool(_install_block(manifest).get(LLM_ACCESS_KEY))


def permitted_models_for_install(manifest) -> list[str]:
    """The allowlist an app is minted with.

    ``install.llm_models`` (a list, or a single name) when the manifest names
    one, else the ``default`` alias.
    """
    declared = _install_block(manifest).get(LLM_MODELS_KEY) or []
    if isinstance(declared, str):
        declared = [declared]
    models = [m for m in declared if isinstance(m, str) and m.strip()]
    return models or list(DEFAULT_PERMITTED_MODELS)


async def provision(proxy, app_id: str, models: list[str] | None = None) -> str | None:
    """Mint — or re-scope an existing — app principal key. Returns the token.

    Reusing the existing row is what keeps install idempotent: a reinstall
    re-scopes the key the container already holds instead of minting a second
    one, so the credential in the running container stays valid.
    """
    if proxy is None:
        return None
    existing = proxy.app_key_state(app_id)
    if existing:
        wanted = list(models or existing.get("allowed_models") or DEFAULT_PERMITTED_MODELS)
        if set(wanted) != set(existing.get("allowed_models") or []):
            await proxy.set_app_models(app_id, wanted)
        return existing.get("key")
    try:
        return await proxy.create_app_key(app_id, models=models)
    except Exception:
        logger.exception("app llm access: minting a key for %s failed", app_id)
        return None


async def inject_install_env(
    request, app_id: str, install_config: dict, manifest=None
) -> str | None:
    """Mint the app's key and merge the proxy env into ``install_config``.

    Returns the minted token, or None when nothing was injected. Two
    properties matter:

    * best-effort — a mint failure leaves the install config untouched, so the
      app installs without a model credential instead of failing to install;
    * non-clobbering — an env key the manifest already sets is left alone. The
      manifest is taOS-owned, so a value pinned there (an external endpoint,
      say) is deliberate, and silently repointing it at the local proxy would
      be a behaviour change nobody asked for.
    """
    if manifest is None or not manifest_opts_in(manifest):
        # Not an opting-in app: nothing to mint. The gate lives here, not only
        # at the install call site, so a caller that forgets it cannot hand every
        # installed app a model credential.
        return None
    state = getattr(getattr(request, "app", None), "state", None)
    proxy = getattr(state, "llm_proxy", None)
    if proxy is None:
        logger.info("app llm access: no llm proxy; %s installs without a key", app_id)
        return None
    token = await provision(proxy, app_id, models=permitted_models_for_install(manifest))
    if not token:
        logger.warning(
            "app llm access: could not mint a key for %s; installing without "
            "OPENAI_BASE_URL/OPENAI_API_KEY", app_id,
        )
        return None

    env = install_config.setdefault("env", {})
    if not isinstance(env, dict):
        logger.warning("app llm access: %s install env is not a mapping; skipping", app_id)
        return token
    url = base_url(int(getattr(proxy, "port", 7834) or 7834))
    injected = env_for(token, url)
    for name, value in injected.items():
        if name in env and env[name] != value:
            logger.info(
                "app llm access: %s manifest already sets %s; leaving it as declared",
                app_id, name,
            )
            continue
        env[name] = value
    return token


async def access_state(proxy, app_id: str) -> dict:
    """The app's LLM access, for the read surface.

    ``key_present`` is ``null`` (rather than ``False``) only when the credential
    store genuinely cannot be read back — a Postgres-backed install keeps its
    virtual keys inside LiteLLM — so a UI can say "unknown" instead of wrongly
    claiming the app has no key.
    """
    state = proxy.app_key_state(app_id) if proxy is not None else None
    if state is not None:
        return {
            "app_id": app_id,
            "permitted_models": list(state.get("allowed_models") or []),
            "key_present": True,
            "key_masked": mask_key(state.get("key")),
        }
    if proxy is not None and not getattr(proxy, "inhouse_keys", False) and getattr(
        proxy, "database_url", None
    ):
        # Postgres-backed: the key exists (or not) inside LiteLLM, out of reach.
        key_present: bool | None = None
    else:
        # No proxy at all, in-house store with no row, or routing-only mode
        # (which mints no per-app keys): we know there is no credential.
        key_present = False
    return {
        "app_id": app_id,
        "permitted_models": [],
        "key_present": key_present,
        "key_masked": None,
    }


def mask_key(key: str | None) -> str | None:
    """Mask a token for display: enough to recognise, not enough to use."""
    if not key:
        return None
    tail = key[-4:] if len(key) > 4 else ""
    return f"sk-taos-…{tail}"


async def set_access(proxy, app_id: str, models: list[str]) -> dict:
    """Apply a model scope to the app, minting its key if it has none yet.

    Returns ``{app_id, permitted_models, key_action}``. ``key_action`` is
    ``rescoped`` (an existing key moved to the new scope, value unchanged — so
    a running container needs no restart), ``minted`` (the app had no key and
    now has one), ``unchanged`` (already at that scope) or ``none`` (the
    credential store could not be written).
    """
    models = list(models)
    if proxy is None:
        return {"app_id": app_id, "permitted_models": models, "key_action": "none"}
    state = proxy.app_key_state(app_id)
    if state is None:
        token = await proxy.create_app_key(app_id, models=models)
        return {
            "app_id": app_id,
            "permitted_models": models,
            "key_action": "minted" if token else "none",
        }
    if list(state.get("allowed_models") or []) == models:
        return {"app_id": app_id, "permitted_models": models, "key_action": "unchanged"}
    rescoped = await proxy.set_app_models(app_id, models)
    return {
        "app_id": app_id,
        "permitted_models": models,
        "key_action": "rescoped" if rescoped else "none",
    }


async def rotate(proxy, app_id: str, models: list[str] | None = None) -> str | None:
    """Mint a FRESH key for the app and drop the old ones. Returns the plaintext.

    This is the only path that returns secret material to a caller, and it does
    so once: the value is written into the app's own settings by whoever asked,
    not stored anywhere else.
    """
    if proxy is None:
        return None
    existing = proxy.app_key_state(app_id)
    scope = list(models or (existing or {}).get("allowed_models") or DEFAULT_PERMITTED_MODELS)
    await proxy.delete_app_key(app_id)
    return await proxy.create_app_key(app_id, models=scope)
