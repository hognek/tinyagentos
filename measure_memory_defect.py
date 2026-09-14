#!/usr/bin/env python3
"""
Measurement test to confirm the memory scope defect.

This test shows that memory routes are NOT protected - they accept
agent tokens WITHOUT memory_read scope, which is the PRIVILEGE HOLE defect.
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
from tinyagentos.auth_middleware import AuthMiddleware
from tinyagentos.auth import AuthManager

async def _wire_test_app(tmp_path):
    """Create a test app with fresh stores."""
    from fastapi import FastAPI
    from tinyagentos.agent_registry_store import AgentRegistryStore
    from tinyagentos.agent_grants_store import AgentGrantsStore
    from tinyagentos.agent_registry_store import load_or_create_signing_keypair
    
    app = FastAPI()
    
    # Add middleware
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
    app.add_middleware(AuthMiddleware)
    
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
        origin="taos-deployed",
        handle="@agent-no-mem",
        # origin="external-selfjoin",  # This would be active without set_status call
    )
    
    # Create agent WITH memory_read scope
    agent_with_memory = await registry.register(
        framework="test",
        display_name="Agent With Memory",
        user_id="admin",
        origin="taos-deployed",
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
def test_memory_scope_defect():
    """Test to determine if memory routes are protected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        app, agent_no_memory, agent_with_memory = asyncio.run(_wire_test_app(tmp_path))
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
        
        print("MEASUREMENT: Testing memory route access without scope protection")
        print("="*80)
        
        # Test with agent WITHOUT memory_read scope
        print("\nTesting /api/user-memory/stats with agent WITHOUT memory_read scope...")
        headers_no = {"Authorization": f"Bearer {token_no_memory}"}
        resp_no = client.get("/api/user-memory/stats", headers=headers_no)
        print(f"  Status: {resp_no.status_code}")
        
        if resp_no.status_code == 200:
            print("  ✓ ACCEPTED - PRIVILEGE HOLE: Memory routes reachable without memory_read scope")
            print("  This is the defect we need to fix!")
            return "privilege_hole"
        elif resp_no.status_code in [401, 403]:
            print(f"  ✗ REFUSED - CONSENT INTEGRITY DEFECT")
            return "consent_integrity"
        else:
            print(f"  ? UNEXPECTED - Status {resp_no.status_code}")
            return "unexpected"

if __name__ == "__main__":
    result = test_memory_scope_defect()
    if result == "privilege_hole":
        print("\n✓ CONFIRMED: This is a PRIVILEGE HOLE defect")
        print("  Memory routes are reachable WITHOUT memory_read scope.")
        print("  We need to add scope checks to the memory routes.")
    sys.exit(0 if result != "unexpected" else 1)