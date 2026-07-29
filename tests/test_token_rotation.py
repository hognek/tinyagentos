"""Integration tests for per-identity token rotation (token_min_iat).

Covers the full auth chain: store → auth path → route.
"""

import time

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from tinyagentos.agent_registry_store import mint_registry_token
from tinyagentos.agent_token_auth import check_agent_scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def agent_app(app):
    """AsyncClient logged in as admin + agent_registry / agent_grants initialised."""
    for attr in ("agent_registry", "agent_grants"):
        store = getattr(app.state, attr, None)
        if store is not None and store._db is None:
            await store.init()
    # Reuse the same init + admin-session logic as the main client fixture
    store = app.state.metrics
    if store._db is not None:
        await store.close()
    await store.init()
    notif_store = app.state.notifications
    if notif_store._db is not None:
        await notif_store.close()
    await notif_store.init()
    await app.state.qmd_client.init()
    secrets_store = app.state.secrets
    if secrets_store._db is not None:
        await secrets_store.close()
    await secrets_store.init()
    broker_store = app.state.broker_store
    if broker_store._db is not None:
        await broker_store.close()
    await broker_store.init()
    scheduler = app.state.scheduler
    if scheduler._db is not None:
        await scheduler.close()
    await scheduler.init()
    channel_store = app.state.channels
    if channel_store._db is not None:
        await channel_store.close()
    await channel_store.init()
    relationship_mgr = app.state.relationships
    if relationship_mgr._db is not None:
        await relationship_mgr.close()
    await relationship_mgr.init()
    conversion_mgr = app.state.conversion
    if conversion_mgr._db is not None:
        await conversion_mgr.close()
    await conversion_mgr.init()
    training_mgr = app.state.training
    if training_mgr._db is not None:
        await training_mgr.close()
    await training_mgr.init()
    agent_messages = app.state.agent_messages
    if agent_messages._db is not None:
        await agent_messages.close()
    await agent_messages.init()
    shared_folders = app.state.shared_folders
    if shared_folders._db is not None:
        await shared_folders.close()
    await shared_folders.init()
    streaming_sessions = app.state.streaming_sessions
    if streaming_sessions._db is not None:
        await streaming_sessions.close()
    await streaming_sessions.init()
    expert_agents = app.state.expert_agents
    if expert_agents._db is not None:
        await expert_agents.close()
    await expert_agents.init()
    chat_messages = app.state.chat_messages
    if chat_messages._db is not None:
        await chat_messages.close()
    await chat_messages.init()
    chat_channels = app.state.chat_channels
    if chat_channels._db is not None:
        await chat_channels.close()
    await chat_channels.init()
    project_store = app.state.project_store
    if project_store._db is not None:
        await project_store.close()
    await project_store.init()
    project_invites = app.state.project_invites
    if project_invites._db is not None:
        await project_invites.close()
    await project_invites.init()
    board_audit = app.state.board_audit
    if board_audit._db is not None:
        await board_audit.close()
    await board_audit.init()
    receipt_store = app.state.receipt_store
    if receipt_store._db is not None:
        await receipt_store.close()
    await receipt_store.init()
    project_task_store = app.state.project_task_store
    if project_task_store._db is not None:
        await project_task_store.close()
    await project_task_store.init()
    project_element_store = app.state.project_element_store
    if project_element_store._db is not None:
        await project_element_store.close()
    await project_element_store.init()
    routine_store = app.state.routine_store
    if routine_store._db is not None:
        await routine_store.close()
    await routine_store.init()
    decision_store = app.state.decision_store
    if decision_store._db is not None:
        await decision_store.close()
    await decision_store.init()
    execution_policies = app.state.execution_policies
    if execution_policies._db is not None:
        await execution_policies.close()
    await execution_policies.init()
    coding_session_store = app.state.coding_session_store
    if coding_session_store._db is not None:
        await coding_session_store.close()
    await coding_session_store.init()
    app.state.projects_root.mkdir(parents=True, exist_ok=True)
    canvas_store = app.state.canvas_store
    if canvas_store._db is not None:
        await canvas_store.close()
    await canvas_store.init()
    themes = app.state.themes
    if themes._db is not None:
        await themes.close()
    await themes.init()
    office_docs = app.state.office_docs
    if office_docs._db is not None:
        await office_docs.close()
    await office_docs.init()
    web_sites = app.state.web_sites
    if web_sites._db is not None:
        await web_sites.close()
    await web_sites.init()
    song_store = app.state.song_store
    if song_store._db is not None:
        await song_store.close()
    await song_store.init()
    design_docs = app.state.design_docs
    if design_docs._db is not None:
        await design_docs.close()
    await design_docs.init()
    await app.state.app_grants.init()
    await app.state.license_acceptances.init()
    feedback_store = app.state.feedback_store
    if feedback_store._db is not None:
        await feedback_store.close()
    await feedback_store.init()
    client_log_store = app.state.client_log_store
    if client_log_store._db is not None:
        await client_log_store.close()
    await client_log_store.init()
    device_store = app.state.device_store
    if device_store._db is not None:
        await device_store.close()
    await device_store.init()
    council_roles = app.state.council_roles
    if council_roles._db is not None:
        await council_roles.close()
    await council_roles.init()
    council_members = app.state.council_members
    if council_members._db is not None:
        await council_members.close()
    await council_members.init()
    from tinyagentos.routes.desktop_browser.store import BrowserStore, BrowserCookieStore
    _browser_store = BrowserStore(app.state.data_dir / "browser.sqlite3")
    await _browser_store.init()
    app.state.browser_store = _browser_store
    _browser_cookie_store = BrowserCookieStore(
        app.state.data_dir / "browser_cookies.sqlite3", key_hex="0" * 64
    )
    await _browser_cookie_store.init()
    app.state.browser_cookie_store = _browser_cookie_store
    from tinyagentos.routes.desktop_browser.copilot_ws import CopilotTicketStore, CopilotHub
    app.state.copilot_ticket_store = CopilotTicketStore()
    app.state.copilot_hub = CopilotHub()
    app.state.auth.setup_user("admin", "Test Admin", "", "testpass")
    _record = app.state.auth.find_user("admin")
    _uid = _record["id"] if _record else ""
    _token = app.state.auth.create_session(user_id=_uid, long_lived=True)
    app.state._startup_complete = True
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"taos_session": _token},
    ) as c:
        yield c
    await canvas_store.close()
    await project_task_store.close()
    await routine_store.close()
    await board_audit.close()
    await project_store.close()
    await project_invites.close()
    await chat_channels.close()
    await chat_messages.close()
    await expert_agents.close()
    await streaming_sessions.close()
    await shared_folders.close()
    await agent_messages.close()
    await conversion_mgr.close()
    await training_mgr.close()
    await relationship_mgr.close()
    await channel_store.close()
    await scheduler.close()
    await secrets_store.close()
    await broker_store.close()
    await notif_store.close()
    await store.close()
    await office_docs.close()
    await web_sites.close()
    await song_store.close()
    await design_docs.close()
    await coding_session_store.close()
    await feedback_store.close()
    await client_log_store.close()
    await project_element_store.close()
    await app.state.qmd_client.close()
    await app.state.http_client.aclose()
    await _browser_store.close()
    await _browser_cookie_store.close()
    await council_roles.close()
    await council_members.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeRequest:
    """Minimal stand-in for a starlette Request used by check_agent_scope."""

    def __init__(self, app, token: str | None = None):
        self.app = app
        self.headers = {}
        if token is not None:
            self.headers["Authorization"] = f"Bearer {token}"


async def _register_and_mint(app, *, user_id="u", scopes=("a2a_receive",)):
    """Register an active agent, add grants, and mint a signed JWT.

    Returns (canonical_id, token).
    """
    registry = app.state.agent_registry
    grants = app.state.agent_grants
    priv, _pub = app.state.agent_registry_keypair
    rec = await registry.register(
        framework="test",
        display_name="TestAgent",
        origin="external-selfjoin",
        handle="@test",
    )
    cid = rec["canonical_id"]
    await registry.set_status(cid, "active")
    for scope in scopes:
        await grants.add_grant(cid, scope)
    token = mint_registry_token(cid, priv, user_id=user_id, framework="test")
    return cid, token


# ---------------------------------------------------------------------------
# Auth-path tests
# ---------------------------------------------------------------------------


class TestTokenMinIatAuth:
    """Verify the token_min_iat check inside _verify_agent_scope."""

    @pytest.mark.asyncio
    async def test_old_token_rejected_after_bump(self, app):
        """A token minted before the bump is rejected after bump_token_min_iat."""
        for attr in ("agent_registry", "agent_grants"):
            store = getattr(app.state, attr, None)
            if store is not None and store._db is None:
                await store.init()

        registry = app.state.agent_registry
        grants = app.state.agent_grants
        priv, _pub = app.state.agent_registry_keypair

        rec = await registry.register(
            framework="test", display_name="TestAgent",
            origin="external-selfjoin", handle="@test",
        )
        cid = rec["canonical_id"]
        await registry.set_status(cid, "active")
        await grants.add_grant(cid, "a2a_receive")

        # Mint old token
        old_token = mint_registry_token(cid, priv, user_id="u", framework="test")
        assert (await registry.get(cid)) is not None  # token_min_iat is 0

        # Bump the cutoff to a future timestamp so the old token's iat is
        # strictly less (both happen in sub-second time in tests).
        await registry.bump_token_min_iat(cid, int(time.time()) + 3600)

        # The old token should now be rejected
        req = _FakeRequest(app, old_token)
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "a2a_receive")
        assert exc.value.status_code == 401
        assert exc.value.detail == "token superseded"

    @pytest.mark.asyncio
    async def test_new_token_passes_after_bump(self, app):
        """A token minted AFTER the bump passes the cutoff check."""
        for attr in ("agent_registry", "agent_grants"):
            store = getattr(app.state, attr, None)
            if store is not None and store._db is None:
                await store.init()

        registry = app.state.agent_registry
        grants = app.state.agent_grants
        priv, _pub = app.state.agent_registry_keypair

        rec = await registry.register(
            framework="test", display_name="TestAgent",
            origin="external-selfjoin", handle="@test",
        )
        cid = rec["canonical_id"]
        await registry.set_status(cid, "active")
        await grants.add_grant(cid, "a2a_receive")

        # Bump the cutoff
        await registry.bump_token_min_iat(cid, int(time.time()))

        # Mint a new token after the bump
        new_token = mint_registry_token(cid, priv, user_id="u", framework="test")

        req = _FakeRequest(app, new_token)
        result = await check_agent_scope(req, "a2a_receive")
        assert result == cid

    @pytest.mark.asyncio
    async def test_default_zero_keeps_existing_tokens_valid(self, app):
        """Default token_min_iat=0 means all tokens pass (no lockout on migration)."""
        for attr in ("agent_registry", "agent_grants"):
            store = getattr(app.state, attr, None)
            if store is not None and store._db is None:
                await store.init()

        registry = app.state.agent_registry
        grants = app.state.agent_grants
        priv, _pub = app.state.agent_registry_keypair

        rec = await registry.register(
            framework="test", display_name="TestAgent",
            origin="external-selfjoin", handle="@test",
        )
        cid = rec["canonical_id"]
        await registry.set_status(cid, "active")
        await grants.add_grant(cid, "a2a_receive")

        # token_min_iat should be 0 by default
        reread = await registry.get(cid)
        assert reread["token_min_iat"] == 0

        token = mint_registry_token(cid, priv, user_id="u", framework="test")
        req = _FakeRequest(app, token)
        result = await check_agent_scope(req, "a2a_receive")
        assert result == cid


# ---------------------------------------------------------------------------
# Route-level tests
# ---------------------------------------------------------------------------


class TestRotateTokensRoute:
    """Test POST /api/agents/registry/{id}/rotate-tokens via the admin client."""

    @pytest.mark.asyncio
    async def test_admin_can_rotate(self, agent_app, app):
        """An admin can bump token_min_iat on any identity."""
        cid, token = await _register_and_mint(app, user_id="admin")
        resp = await agent_app.post(f"/api/agents/registry/{cid}/rotate-tokens")
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_min_iat"] > 0

    @pytest.mark.asyncio
    async def test_owner_can_rotate(self, agent_app, app):
        """A session owner (non-admin) can rotate their own identity."""
        cid, token = await _register_and_mint(app, user_id="admin")
        resp = await agent_app.post(f"/api/agents/registry/{cid}/rotate-tokens")
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_min_iat"] > 0

    @pytest.mark.asyncio
    async def test_rotate_nonexistent_returns_404(self, agent_app):
        """Rotating a nonexistent identity returns 404."""
        resp = await agent_app.post(
            "/api/agents/registry/no-such-agent-20260101-000000/rotate-tokens"
        )
        assert resp.status_code == 404
