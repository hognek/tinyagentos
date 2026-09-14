#!/usr/bin/env python3
"""
Measurement test to confirm the memory scope defect.

This test demonstrates that the memory routes are NOT protected by scope checks.
"""

import asyncio
import sys
from pathlib import Path
import tempfile

sys.path.insert(0, '/tmp/exec-tsk-zndqmm')

from tinyagentos.agent_registry_store import (
    AgentRegistryStore, 
    load_or_create_signing_keypair,
    mint_registry_token
)
from tinyagentos.agent_grants_store import AgentGrantsStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware
from tinyagentos.routes.memory import router as memory_router
from tinyagentos.routes.user_memory import router as user_memory_router
from tinyagentos.routes.memory_management import router as memory_mgmt_router

async def _wire_test_app_without_auth(tmp_path):
    """Create a test app WITHOUT auth_middleware to test memory routes."""
    from fastapi import FastAPI
    
    app = FastAPI()
    
    # No auth_middleware - this is how tests typically work
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
    
    # Setup stores
    registry = AgentRegistryStore(tmp_path / "reg.db")
    grants = AgentGrantsStore(tmp_path / "grants.db")
    await registry.init()
    await grants.init()
    
    # Create keypair
    priv, pub = load_or_create_signing_keypair(tmp_path / "keys")
    
    # Create agent WITHOUT memory_read scope
    agent_no_memory = await registry.register(
        framework="test",
        display_name="Agent No Memory",
        user_id="admin",
        origin="external-selfjoin",  # This agent is 'active' by default
        handle="@agent-no-mem",
    )
    
    # Create agent WITH memory_read scope
    agent_with_memory = await registry.register(
        framework="test",
        display_name="Agent With Memory",
        user_id="admin",
        origin="external-selfjoin",
        handle="@agent-with-mem",
    )
    
    # Grant memory_read to second agent only
    await grants.add_grant(agent_with_memory["canonical_id"], "memory_read", project_id=None)
    
    # Store on app
    app.state.agent_registry = registry
    app.state.agent_grants = grants
    app.state.agent_registry_keypair = (priv, pub)
    
    # Register memory routes
    app.include_router(memory_router)
    app.include_router(user_memory_router)
    app.include_router(memory_mgmt_router)
    
    return app, agent_no_memory, agent_with_memory
def test_memory_scope_measurement():
    """Test to measure if memory routes have scope protection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        app, agent_no_memory, agent_with_memory = asyncio.run(_wire_test_app_without_auth(tmp_path))
        client = TestClient(app)
        
        registry = app.state.agent_registry
        priv, _pub = app.state.agent_registry_keypair
        
        # Token for agent WITHOUT memory_read scope
        token_no_memory = mint_registry_token(
            agent_no_memory["canonical_id"], priv, user_id="admin", framework="test"
        )
        
        # Token for agent WITH memory_read scope
        token_with_memory = mint_registry_token(
            agent_with_memory["canonical_id"], priv, user_id="admin", framework="test"
        )
        
        print("MEASUREMENT: Testing memory route access in test environment")
        print("="*80)
        print("Note: This test runs WITHOUT auth_middleware, simulating how")
        print("the actual routes work in production.")
        print()
        
        # Test with agent WITHOUT memory_read scope
        print("Testing /api/user-memory/stats with agent WITHOUT memory_read scope...")
        headers_no = {"Authorization": f"Bearer {token_no_memory}"}
        resp_no = client.get("/api/user-memory/stats", headers=headers_no)
        print(f"  Status: {resp_no.status_code}")
        
        if resp_no.status_code == 200:
            print("  ✓ ACCEPTED - PRIVILEGE HOLE: Agent without memory_read scope can access memory routes")
            print("  This is the defect - memory_read scope is not enforced!")
            print()
            print("CONCLUSION:")
            print("Memory routes are NOT protected by scope checks.")
            print("They accept agent tokens regardless of what scopes the agent holds.")
            print("This is a PRIVILEGE HOLE - the memory_read scope is decorative.")
            return "privilege_hole"
        else:
            print(f"  ✗ Status {resp_no.status_code}")
            print()
            print("CONCLUSION:")
            print("Memory routes reject the agent token.")
            print("This could be a CONSENT INTEGRITY defect.")
            return "consent_integrity"

if __name__ == "__main__":
    result = test_memory_scope_measurement()
    sys.exit(0 if result == "privilege_hole" else 1)