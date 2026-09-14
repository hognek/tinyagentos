#!/usr/bin/env python3
"""
Simplified test to determine the memory scope defect type.
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
from tinyagentos.auth_middleware import AuthMiddleware
from fastapi.middleware.cors import CORSMiddleware
from tinyagentos.routes.memory import router as memory_router
from tinyagentos.routes.user_memory import router as user_memory_router
from tinyagentos.routes.memory_management import router as memory_mgmt_router
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
    )
    
    # Create agent WITH memory_read scope
    agent_with_memory = await registry.register(
        framework="test",
        display_name="Agent With Memory",
        user_id="admin",
        origin="taos-deployed",
        handle="@agent-with-mem",
    )
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
    """Quick test to determine defect type."""
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
        
        # Test a simple memory route
        headers_no = {"Authorization": f"Bearer {token_no_memory}"}
        headers_with = {"Authorization": f"Bearer {token_with_memory}"}
        
        # Test user memory stats route (simple GET)
        print("Testing /api/user-memory/stats with agent WITHOUT memory_read...")
        resp_no = client.get("/api/user-memory/stats", headers=headers_no)
        print(f"  Status: {resp_no.status_code}, Body: {resp_no.json()}")
        
        print("\nTesting /api/user-memory/stats with agent WITH memory_read...")
        resp_with = client.get("/api/user-memory/stats", headers=headers_with)
        print(f"  Status: {resp_with.status_code}, Body: {resp_with.json()}")
        
        # Determine defect type
        if resp_no.status_code == 401 or resp_no.status_code == 403:
            print("\n✓ CONSENT INTEGRITY DEFECT: Agent without memory_read is REFUSED")
            print("  The approval UI reports success, but the operator cannot tell")
            print("  that memory_read is a grantable but nongated scope.")
            print("  This matches #2095 class.")
            return "consent_integrity"
        elif resp_no.status_code == 200:
            print("\n✗ PRIVILEGE HOLE: Agent without memory_read is ACCEPTED")
            print("  Memory routes are reachable WITHOUT memory_read scope.")
            print("  This is a privilege hole - memory_read is decorative.")
            return "privilege_hole"
        else:
            print(f"\n? UNEXPECTED: Status {resp_no.status_code}")
            return "unexpected"
if __name__ == "__main__":
    result = test_memory_scope_defect()
    sys.exit(0 if result != "unexpected" else 1)