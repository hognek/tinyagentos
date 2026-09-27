"""LiteLLM custom_auth hook backed by taOS's in-house key store.

Wired via ``general_settings.custom_auth`` in the generated LiteLLM config
(through a config-dir ``taos_auth.py`` shim, like the callback). This lets
LiteLLM authorize per-agent keys against ``LiteLLMKeyStore`` instead of its
Postgres ``LiteLLM_VerificationToken`` table, so virtual keys work with NO
``DATABASE_URL`` and no prisma (the ARM / no-Postgres fix).

The hook reads two env vars exported by ``LLMProxy.start`` into the
subprocess:
  - ``LITELLM_MASTER_KEY``   -> admin passthrough
  - ``TAOS_LITELLM_KEYSTORE`` -> path to the SQLite key store

Per-agent and per-app model scoping is enforced HERE (read the requested model
from the body and reject out-of-scope calls) so correctness does not depend on
LiteLLM's historically-flaky post-auth model-allowlist path. The returned
object also carries the allowlist + metadata so LiteLLM's own enforcement
and taOS's usage callback both work.

An app principal (#613) is a row whose ``kind`` is ``app``: the same allowlist
rule and the same store, minus the agent budget gate (an app has no LLM
budget, exactly as in the in-process gateway).
"""
from __future__ import annotations

import logging
import os
import secrets

from tinyagentos.litellm_keystore import (
    APP_PRINCIPAL_PREFIX,
    KIND_APP,
)

logger = logging.getLogger(__name__)

_store = None
_store_path = None
_budget_store_cache = None
_budget_store_cache_path = None


def model_scope_error(kind: str, allowed: list[str], requested: str | None) -> str | None:
    """The allowlist verdict for one request: a refusal detail, or None.

    Pure and litellm-free so the rule is testable without the proxy extra, and
    so the hook has exactly one place to get it wrong. An EMPTY allowlist is
    deny-all (the keystore's ``mint`` contract) -- never treated as "no
    restriction", which is how LiteLLM reads an empty ``models`` list.
    """
    noun = "app" if kind == KIND_APP else "agent"
    if not allowed:
        return f"no models are permitted for this {noun}"
    if requested and requested not in allowed:
        return f"model {requested!r} is not permitted for this {noun}"
    return None


def key_alias_for(principal: str, kind: str) -> str:
    """The LiteLLM-side name for a principal.

    ``app:open-webui`` -> ``taos-app-open-webui``; an agent keeps the historical
    ``taos-<name>``.
    """
    if kind == KIND_APP and principal.startswith(APP_PRINCIPAL_PREFIX):
        return "taos-app-" + principal[len(APP_PRINCIPAL_PREFIX):]
    return f"taos-{principal}"


def _keystore():
    """Lazily open (and cache) the keystore from the env-provided path."""
    global _store, _store_path
    path = os.environ.get("TAOS_LITELLM_KEYSTORE")
    if not path:
        return None
    if _store is None or _store_path != path:
        from tinyagentos.litellm_keystore import LiteLLMKeyStore
        _store = LiteLLMKeyStore(path)
        _store_path = path
    return _store


def _budget_store():
    """Lazily open (and cache) the budget store from the env-provided path.

    Returns None when the env var is unset — budgets are opt-in, so a
    deploy that never configured them fails OPEN (no check at all) rather
    than rejecting every call.
    """
    global _budget_store_cache, _budget_store_cache_path
    path = os.environ.get("TAOS_AGENT_BUDGETS")
    if not path:
        return None
    if _budget_store_cache is None or _budget_store_cache_path != path:
        from tinyagentos.agent_budget_store import AgentBudgetStore
        _budget_store_cache = AgentBudgetStore(path)
        _budget_store_cache_path = path
    return _budget_store_cache


async def _requested_model(request) -> str | None:
    """Best-effort read of the model from the request body (for scope check).

    Never raises: a body we cannot parse just means we skip the in-hook model
    check and rely on the returned allowlist.
    """
    try:
        body = await request.json()
    except Exception:
        return None
    if isinstance(body, dict):
        m = body.get("model")
        return m if isinstance(m, str) else None
    return None


async def user_api_key_auth(request, api_key: str):
    """Authorize an incoming key against the taOS key store.

    Returns a ``UserAPIKeyAuth`` on success; raises ``fastapi.HTTPException``
    (401/403) otherwise. The master key is admin (full access).
    """
    from fastapi import HTTPException
    from litellm.proxy._types import UserAPIKeyAuth

    master = os.environ.get("LITELLM_MASTER_KEY")
    if master and secrets.compare_digest(api_key, master):
        return UserAPIKeyAuth(api_key=api_key)

    store = _keystore()
    if store is None:
        # Misconfiguration: in-house auth selected but no store path. Refuse
        # rather than silently allow.
        logger.error("litellm_auth: TAOS_LITELLM_KEYSTORE not set; rejecting key")
        raise HTTPException(status_code=401, detail="auth store unavailable")

    rec = store.lookup(api_key)
    if rec is None:
        raise HTTPException(status_code=401, detail="invalid key")

    principal = rec["agent"]
    kind = rec.get("kind") or "agent"
    allowed = rec["allowed_models"] or []

    # Hard-stop: reject calls for an agent that has exceeded its LLM
    # budget. Fails open (no check) when budgets are not configured at all
    # (env var unset), but once TAOS_AGENT_BUDGETS is set, an over-budget
    # agent is blocked before a completion is ever dispatched. App principals
    # are not agents and have no agent budget: skipping the gate here matches
    # the in-process gateway, which checks budgets for kind "agent" only.
    budget_store = _budget_store()
    if kind != KIND_APP and budget_store is not None and budget_store.is_over_budget(principal):
        raise HTTPException(
            status_code=429,
            detail=f"agent '{principal}' has exceeded its LLM budget",
        )

    # Defense in depth: enforce the model allowlist in-hook so correctness does
    # not depend on LiteLLM's post-auth enforcement (which is disabled here via
    # custom_auth_run_common_checks=False). An empty allowlist is deny-all per
    # the keystore's mint() contract — do NOT short-circuit it, because
    # returning UserAPIKeyAuth(models=[]) would be read by LiteLLM as "no
    # restriction" (allow-all), the opposite intent.
    refusal = model_scope_error(kind, allowed, await _requested_model(request))
    if refusal is not None:
        raise HTTPException(status_code=403, detail=refusal)

    return UserAPIKeyAuth(
        api_key=api_key,
        key_alias=key_alias_for(principal, kind),
        models=list(allowed),
        metadata={
            "agent": principal,
            "principal": principal,
            "principal_kind": kind,
            "managed_by": "tinyagentos",
        },
    )
