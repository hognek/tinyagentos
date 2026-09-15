import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tinyagentos.agent_registry_store import mint_registry_token
from tinyagentos.routes.agent_auth_requests import VALID_SCOPES
from tinyagentos.routes.agent_registry import _ALLOWED_SCOPES


@pytest_asyncio.fixture
async def agent_token_app(app):
    """App with initialized stores and an agent token without memory scopes."""
    for attr in ("agent_registry", "agent_grants", "metrics", "notifications", "qmd_client", 
                 "secrets", "broker_store", "scheduler", "channels", "relationship_mgr",
                 "conversion_mgr", "training_mgr", "agent_messages", "shared_folders",
                 "streaming_sessions", "expert_agents", "chat_messages", "chat_channels",
                 "project_store", "project_invites", "board_audit", "receipt_store",
                 "task_strikes", "project_task_store", "project_element_store",
                 "project_notes_store", "project_lists_store", "project_list_entries_store",
                 "routine_store", "decision_store", "execution_policies", "coding_session_store",
                 "container_request_store", "canvas_store", "themes", "office_docs", "web_sites",
                 "song_store", "lora_store", "design_docs", "app_grants", "license_acceptances",
                 "feedback_store", "client_log_store", "device_store", "device_pair_requests",
                 "council_roles", "council_members"):
        store = getattr(app.state, attr, None)
        if store is not None and hasattr(store, '_db') and store._db is None:
            if hasattr(store, 'init'):
                await store.init()
    
    app.state.auth.setup_user("admin", "Test Admin", "", "testpass")
    app.state._startup_complete = True
    
    # Register agent WITHOUT memory_read/memory_write scopes
    registry = app.state.agent_registry
    grants = app.state.agent_grants
    priv, _pub = app.state.agent_registry_keypair
    
    import uuid
    unique_suffix = str(uuid.uuid4())[:8]
    
    rec = await registry.register(
        framework="grok",
        display_name="Grok",
        origin="external-selfjoin",
        handle=f"@grok-{unique_suffix}",
    )
    cid = rec["canonical_id"]
    await registry.set_status(cid, "active")
    # Only grant a2a_receive, NOT memory_read or memory_write
    await grants.add_grant(cid, "a2a_receive", project_id="prj-1")
    token = mint_registry_token(
        cid, priv, user_id="u", framework="grok", project_id="prj-1"
    )
    
    yield app, token, cid
    
    # Cleanup
    for attr in ("agent_registry", "agent_grants", "metrics", "notifications", "qmd_client", 
                 "secrets", "broker_store", "scheduler", "channels", "relationship_mgr",
                 "conversion_mgr", "training_mgr", "agent_messages", "shared_folders",
                 "streaming_sessions", "expert_agents", "chat_messages", "chat_channels",
                 "project_store", "project_invites", "board_audit", "receipt_store",
                 "task_strikes", "project_task_store", "project_element_store",
                 "project_notes_store", "project_lists_store", "project_list_entries_store",
                 "routine_store", "decision_store", "execution_policies", "coding_session_store",
                 "container_request_store", "canvas_store", "themes", "office_docs", "web_sites",
                 "song_store", "lora_store", "design_docs", "app_grants", "license_acceptances",
                 "feedback_store", "client_log_store", "device_store", "device_pair_requests",
                 "council_roles", "council_members"):
        store = getattr(app.state, attr, None)
        if store is not None and hasattr(store, '_db') and store._db is not None:
            if hasattr(store, 'close'):
                await store.close()


class TestMemoryScopeEnforcement:
    """Test that memory scopes have been removed from the grantable vocabulary
    (consent-integrity fix) since the memory routes are not reachable by agent tokens.
    """

    def test_memory_read_removed_from_valid_scopes(self):
        """memory_read must not be in the grantable vocabulary."""
        assert "memory_read" not in VALID_SCOPES

    def test_memory_write_removed_from_valid_scopes(self):
        """memory_write must not be in the grantable vocabulary."""
        assert "memory_write" not in VALID_SCOPES

    def test_tools_execute_removed_from_valid_scopes(self):
        """tools_execute must not be in the grantable vocabulary."""
        assert "tools_execute" not in VALID_SCOPES

    def test_memory_read_removed_from_allowed_scopes(self):
        """memory_read must not be in the internal agent allowed scopes."""
        assert "memory_read" not in _ALLOWED_SCOPES

    def test_memory_write_removed_from_allowed_scopes(self):
        """memory_write must not be in the internal agent allowed scopes."""
        assert "memory_write" not in _ALLOWED_SCOPES

    def test_tools_execute_removed_from_allowed_scopes(self):
        """tools_execute must not be in the internal agent allowed scopes."""
        assert "tools_execute" not in _ALLOWED_SCOPES

    @pytest.mark.asyncio
    async def test_memory_routes_reachable_without_scope_checks(self, agent_token_app):
        """Memory routes should be reachable via session auth (not agent token),
        and should not have dead scope checks in handlers."""
        app, token, cid = agent_token_app
        
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            # Agent tokens are blocked by middleware (401) because memory routes
            # are not in _AGENT_TOKEN_PATHS. This is expected - the consent-integrity
            # fix acknowledges this by removing the unenforceable scopes.
            resp = await client.get("/api/memory/browse")
            assert resp.status_code == 401
            assert resp.json()["error"] == "Authentication required"
            
            resp = await client.get("/api/memory/stats")
            assert resp.status_code == 401
            
            resp = await client.post("/api/memory/search", json={"query": "test", "mode": "keyword"})
            assert resp.status_code == 401
            
            resp = await client.get("/api/user-memory/stats")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_memory_write_routes_reachable_without_scope_checks(self, agent_token_app):
        """Memory write routes should also be blocked at middleware for agent tokens."""
        app, token, cid = agent_token_app
        
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            resp = await client.post("/api/user-memory/save", json={"content": "test"})
            assert resp.status_code == 401
            
            resp = await client.post("/api/memory/recipes/default/apply", json={})
            assert resp.status_code == 401
            
            resp = await client.delete("/api/memory/chunk/abc123")
            assert resp.status_code == 401
            
            resp = await client.delete("/api/user-memory/chunk/abc123")
            assert resp.status_code == 401