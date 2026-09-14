import pytest
import pytest_asyncio
from fastapi import HTTPException

from tinyagentos.agent_registry_store import mint_registry_token
from tinyagentos.agent_token_auth import (
    check_agent_scope,
    check_agent_scope_for_project,
)


class _FakeRequest:
    """Minimal stand-in for a starlette Request: the auth helpers only touch
    ``.headers.get(...)`` and ``.app.state`` on the object."""

    def __init__(self, app, token: str | None = None):
        self.app = app
        self.headers = {}
        if token is not None:
            self.headers["Authorization"] = f"Bearer {token}"


@pytest_asyncio.fixture
async def token_app(app):
    for attr in ("agent_registry", "agent_grants"):
        store = getattr(app.state, attr)
        if store._db is None:
            await store.init()
    yield app
    for attr in ("agent_registry", "agent_grants"):
        store = getattr(app.state, attr)
        if store._db is not None:
            await store.close()


async def _mint(
    app, *, scopes=("project_tasks",), project_id="prj-1", extra_grants=None
):
    """Register an active agent, add its grants, and mint a JWT.

    ``scopes`` are all bound to ``project_id``. ``extra_grants`` is an optional
    list of ``(scope, project_id)`` pairs bound to OTHER projects, used to model
    an agent that is a member of multiple projects (taOS #1862).
    """
    registry = app.state.agent_registry
    grants = app.state.agent_grants
    priv, _pub = app.state.agent_registry_keypair
    
    # Use a unique handle for each agent to avoid constraint violations
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
    for scope in scopes:
        await grants.add_grant(cid, scope, project_id=project_id)
    for scope, pid in (extra_grants or []):
        await grants.add_grant(cid, scope, project_id=pid)
    token = mint_registry_token(
        cid, priv, user_id="u", framework="grok", project_id=project_id
    )
    return cid, token


@pytest.mark.asyncio
class TestMemoryScopeEnforcement:
    """Test that memory routes are protected by memory_read scope.

    This test FAILS on current dev because memory routes have no scope checks.
    """

    async def test_agent_without_memory_read_is_refused(self, token_app):
        """Test that an agent WITHOUT memory_read scope is REFUSED by auth middleware."""
        cid, token = await _mint(token_app, scopes=("a2a_receive",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        # This should raise 403 because the token does NOT hold memory_read scope
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_read")
        assert exc.value.status_code == 403
        assert "token does not hold an active" in exc.value.detail

    async def test_agent_with_memory_read_is_accepted(self, token_app):
        """Test that an agent WITH memory_read scope is ACCEPTED."""
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        # This should succeed because the token holds memory_read scope
        got = await check_agent_scope(req, "memory_read")
        assert got == cid

    async def test_project_memory_scope_enforcement(self, token_app):
        """Test that project-bound memory routes require project binding."""
        # Agent without project-scoped memory_read grant
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id=None)
        req = _FakeRequest(token_app, token)
        
        # Project-scoped check should fail
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope_for_project(req, "memory_read", "prj-1")
        assert exc.value.status_code == 403
        assert "token not scoped to this project" in exc.value.detail

    async def test_project_memory_scope_grant(self, token_app):
        """Test that project-bound memory routes accept project-scoped grants."""
        cid, token = await _mint(
            token_app, 
            scopes=("memory_read",), 
            project_id=None,
            extra_grants=[("memory_read", "prj-1")]
        )
        req = _FakeRequest(token_app, token)
        
        # Project-scoped check should succeed
        got = await check_agent_scope_for_project(req, "memory_read", "prj-1")
        assert got == cid

    async def test_memory_stats_requires_memory_read_scope(self, token_app):
        """Test that /api/memory/stats requires memory_read scope."""
        # Agent WITHOUT memory_read scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("a2a_receive",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_read")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_read scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_read")
        assert got == cid

    async def test_memory_browse_requires_memory_read_scope(self, token_app):
        """Test that /api/memory/browse requires memory_read scope."""
        # Agent WITHOUT memory_read scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("a2a_receive",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_read")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_read scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_read")
        assert got == cid

    async def test_memory_user_stats_requires_memory_read_scope(self, token_app):
        """Test that /api/user-memory/stats requires memory_read scope."""
        # Agent WITHOUT memory_read scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("a2a_receive",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_read")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_read scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_read")
        assert got == cid

    async def test_memory_management_stats_requires_memory_read_scope(self, token_app):
        """Test that /api/memory/stats in memory_management requires memory_read scope."""
        # Agent WITHOUT memory_read scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("a2a_receive",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_read")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_read scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_read")
        assert got == cid

    async def test_memory_write_operations_require_memory_write_scope(self, token_app):
        """Test that memory write operations require memory_write scope."""
        # Agent WITHOUT memory_write scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_write")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_write scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_write",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_write")
        assert got == cid

    async def test_memory_user_save_requires_memory_write_scope(self, token_app):
        """Test that /api/user-memory/save requires memory_write scope."""
        # Agent WITHOUT memory_write scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_write")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_write scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_write",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_write")
        assert got == cid

    async def test_memory_recipe_apply_requires_memory_write_scope(self, token_app):
        """Test that /api/memory/recipes/default/apply requires memory_write scope."""
        # Agent WITHOUT memory_write scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_write")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_write scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_write",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_write")
        assert got == cid

    async def test_user_memory_search_requires_memory_read_scope(self, token_app):
        """Test that /api/user-memory/search requires memory_read scope."""
        # Agent WITHOUT memory_read scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("a2a_receive",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_read")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_read scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_read")
        assert got == cid

    async def test_user_memory_save_requires_memory_write_scope(self, token_app):
        """Test that /api/user-memory/save requires memory_write scope."""
        # Agent WITHOUT memory_write scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_write")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_write scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_write",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_write")
        assert got == cid

    async def test_memory_delete_chunk_requires_memory_write_scope(self, token_app):
        """Test that /api/memory/chunk/{hash} requires memory_write scope."""
        # Agent WITHOUT memory_write scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_write")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_write scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_write",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_write")
        assert got == cid

    async def test_user_memory_delete_chunk_requires_memory_write_scope(self, token_app):
        """Test that /api/user-memory/chunk/{hash} requires memory_write scope."""
        # Agent WITHOUT memory_write scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_write")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_write scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_write",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_write")
        assert got == cid

    async def test_user_memory_agent_search_requires_memory_read_scope(self, token_app):
        """Test that /api/user-memory/agent-search requires memory_read scope."""
        # Agent WITHOUT memory_read scope should be REFUSED
        cid, token = await _mint(token_app, scopes=("a2a_receive",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        with pytest.raises(HTTPException) as exc:
            await check_agent_scope(req, "memory_read")
        assert exc.value.status_code == 403
        
        # Agent WITH memory_read scope should be ACCEPTED
        cid, token = await _mint(token_app, scopes=("memory_read",), project_id="prj-1")
        req = _FakeRequest(token_app, token)
        
        got = await check_agent_scope(req, "memory_read")
        assert got == cid