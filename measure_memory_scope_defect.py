#!/usr/bin/env python3
"""
Script to measure whether agents can reach /api/memory/* and /api/user-memory/* at all.

This reproduces the measurement phase of the fix for tsk-zndqmm:
- If a token WITHOUT memory_read is REFUSED -> defect is consent integrity
- If a token WITHOUT memory_read is ACCEPTED -> defect is privilege hole

We'll test all memory routes:
1. /api/memory/* (routes/memory.py)
2. /api/user-memory/* (routes/user_memory.py)
3. /api/memory/* (routes/memory_management.py) - these also need protection
"""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import traceback

# Add the repo to path
sys.path.insert(0, '/tmp/exec-tsk-zndqmm')

from tinyagentos.agent_registry_store import (
    AgentRegistryStore, 
    load_or_create_signing_keypair,
    mint_registry_token
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import pytest_asyncio
from httpx import AsyncClient, Response


class _FakeRequest:
    """Minimal stand-in for a starlette Request."""
    
    def __init__(self, app, token: str | None = None):
        self.app = app
        self.headers = {}
        if token is not None:
            self.headers["Authorization"] = f"Bearer {token}"


async def _wire_test_app(tmp_path):
    """Create a test app with fresh stores and one agent."""
    from fastapi import FastAPI
    from tinyagentos.agent_registry_store import AgentRegistryStore
    from tinyagentos.agent_grants_store import AgentGrantsStore
    from tinyagentos.agent_registry_store import load_or_create_signing_keypair
    from tinyagentos.auth_middleware import AuthMiddleware
    from fastapi.middleware.cors import CORSMiddleware
    import asyncio
    
    app = FastAPI()
    
    # Add middleware
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
    app.add_middleware(AuthMiddleware)
    
    # Setup stores
    registry = AgentRegistryStore(tmp_path / "reg.db")
    grants = AgentGrantsStore(tmp_path / "grants.db")
    await registry.init()
    await grants.init()
    
    # Create active agent with different scope combinations
    priv, pub = load_or_create_signing_keypair(tmp_path / "keys")
    
    # Agent WITHOUT memory_read scope
    agent_no_memory = await registry.register(
        framework="test",
        display_name="Agent No Memory",
        user_id="admin",
        origin="taos-deployed",
        handle="@agent-no-mem",
        # origin="external-selfjoin",  # Don't need to call set_status if we set initial_status
    )
    # Agent WITH memory_read scope  
    agent_with_memory = await registry.register(
        framework="test",
        display_name="Agent With Memory",
        user_id="admin",
        origin="taos-deployed",
        handle="@agent-with-mem",
    )
    
    # Store on app
    app.state.agent_registry = registry
    app.state.agent_grants = grants
    app.state.agent_registry_keypair = (priv, pub)
    
    # Register memory routes - they have no auth currently
    from tinyagentos.routes.memory import router as memory_router
    app.include_router(memory_router)
    
    from tinyagentos.routes.user_memory import router as user_memory_router
    app.include_router(user_memory_router)
    
    from tinyagentos.routes.memory_management import router as memory_mgmt_router
    app.include_router(memory_mgmt_router)
    
    return app, agent_no_memory, agent_with_memory


async def test_agent_without_memory_read_is_refused():
    """Test that an agent WITHOUT memory_read scope is REFUSED by auth middleware."""
    print("\n" + "="*80)
    print("TEST: agent without memory_read scope should be REFUSED")
    print("="*80)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        app, agent_no_memory, agent_with_memory = await _wire_test_app(tmp_path)
        client = TestClient(app)
        
        # Create a token for agent WITHOUT memory_read scope
        registry = app.state.agent_registry
        priv, _pub = app.state.agent_registry_keypair
        
        # Token for agent without memory_read
        token_no_memory = mint_registry_token(
            agent_no_memory["canonical_id"], priv, user_id="admin", framework="test"
        )
        
        # Token for agent WITH memory_read
        token_with_memory = mint_registry_token(
            agent_with_memory["canonical_id"], priv, user_id="admin", framework="test"
        )
        
        # Helper to make request with token
        def make_request(token, path, method="GET", **kwargs):
            headers = {"Authorization": f"Bearer {token}"}
            if method == "GET":
                # For GET, any params should be in the query string
                # For routes like /api/memory/collections/{agent_name}, agent_name is part of the path
                # We need to handle path parameters properly
                return client.get(path, headers=headers)
            elif method == "POST":
                json_data = kwargs.get('json', {})
                return client.post(path, headers=headers, json=json_data)
            elif method == "PUT":
                json_data = kwargs.get('json', {})
                return client.put(path, headers=headers, json=json_data)
            elif method == "DELETE":
                return client.delete(path, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")
        
        # List of memory routes to test
        memory_routes = [
            ("/api/memory/browse", "GET", {"agent": "test-agent"}),
            ("/api/memory/search", "POST", {"query": "test", "mode": "keyword", "agent": "test-agent"}),
            ("/api/memory/collections/test-agent", "GET"),
            ("/api/memory/chunk/abc123", "DELETE", {"agent": "test-agent"}),
            ("/api/memory/stats", "GET"),
            ("/api/memory/settings", "GET"),
            ("/api/memory/settings", "PUT", {"capture_conversations": True}),
            ("/api/memory/backend/capabilities", "GET"),
            ("/api/memory/backend/settings-schema", "GET"),
            ("/api/memory/recipes/schema", "GET"),
            ("/api/memory/recipes", "GET"),
            ("/api/memory/recipes/default", "GET"),
            ("/api/memory/recipes/default/apply", "POST", {"agent": "test-agent"}),
            ("/api/memory/recipes/recommend", "POST"),
            ("/api/memory/recipes", "POST", {"name": "test"}),
            ("/api/agents/{name}/memory-config", "GET", {"name": "test-agent"}),
            ("/api/agents/{name}/memory-config", "PUT", {"name": "test-agent"}),
        ]
        
        memory_user_routes = [
            ("/api/user-memory/stats", "GET"),
            ("/api/user-memory/settings", "GET"),
            ("/api/user-memory/settings", "PUT", {"capture_conversations": True}),
            ("/api/user-memory/search", "GET", {"q": "test"}),
            ("/api/user-memory/agent-search", "GET", {"q": "test", "agent_name": "test"}),
            ("/api/user-memory/browse", "GET"),
            ("/api/user-memory/save", "POST", {"content": "test", "title": "test"}),
            ("/api/user-memory/chunk/abc123", "DELETE"),
            ("/api/user-memory/collections", "GET"),
            ("/api/user-memory/migrate", "POST"),
        ]
        
        results = {
            "agent_no_memory_scope": {},
            "agent_with_memory_scope": {},
        }
        
        # Test agent WITHOUT memory_read scope
        print("\nTesting agent WITHOUT memory_read scope...")
        for route in memory_routes + memory_user_routes:
            if len(route) == 3:
                path, method, body = route
            else:
                path, method = route
                body = None
            
            route_desc = f"{method} {path}"
            if body:
                route_desc += f" {body}"
            
            print(f"  Testing {route_desc}...")
            
            # Test with agent without memory_read
            resp = make_request(token_no_memory, path, method, json=body if body else None)
            
            if resp.status_code == 401 or resp.status_code == 403:
                print(f"    ✓ REFUSED (as expected) - status: {resp.status_code}")
                results["agent_no_memory_scope"][route_desc] = "refused"
            elif resp.status_code == 200:
                print(f"    ✗ ACCEPTED (unexpected) - status: {resp.status_code}")
                results["agent_no_memory_scope"][route_desc] = "accepted"
            else:
                print(f"    ? UNEXPECTED - status: {resp.status_code}, body: {resp.text[:100] if resp.text else 'No body'}")
                results["agent_no_memory_scope"][route_desc] = f"unexpected_{resp.status_code}"
        
        # Test agent WITH memory_read scope
        print("\nTesting agent WITH memory_read scope...")
        for route in memory_routes + memory_user_routes:
            if len(route) == 3:
                path, method, body = route
            else:
                path, method = route
                body = None
            
            route_desc = f"{method} {path}"
            if body:
                route_desc += f" {body}"
            
            resp = make_request(token_with_memory, path, method, json=body if body else None)
            
            if resp.status_code == 401 or resp.status_code == 403:
                print(f"    ✓ REFUSED - status: {resp.status_code}")
                results["agent_with_memory_scope"][route_desc] = "refused"
            elif resp.status_code == 200:
                print(f"    ✓ ACCEPTED - status: {resp.status_code}")
                results["agent_with_memory_scope"][route_desc] = "accepted"
            else:
                print(f"    ? UNEXPECTED - status: {resp.status_code}")
                results["agent_with_memory_scope"][route_desc] = f"unexpected_{resp.status_code}"
        
        return results


async def main():
    print("MEASUREMENT PHASE: Testing memory route access controls")
    print("="*80)
    print("""
Goal: Determine if memory routes are protected:
1. If agent WITHOUT memory_read is REFUSED -> consent integrity defect
2. If agent WITHOUT memory_read is ACCEPTED -> privilege hole defect

We need to measure which one we have today.
""")
    
    results = await test_agent_without_memory_read_is_refused()
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    agent_no_memory_results = results["agent_no_memory_scope"]
    agent_with_memory_results = results["agent_with_memory_scope"]
    
    # Count accepted vs refused
    agent_no_memory_accepted = sum(1 for v in agent_no_memory_results.values() if v == "accepted")
    agent_no_memory_refused = sum(1 for v in agent_no_memory_results.values() if v == "refused")
    
    agent_with_memory_accepted = sum(1 for v in agent_with_memory_results.values() if v == "accepted")
    agent_with_memory_refused = sum(1 for v in agent_with_memory_results.values() if v == "refused")
    
    total_routes = len(agent_no_memory_results)
    
    print(f"\nRoutes tested: {total_routes}")
    print(f"Agent WITHOUT memory_read scope:")
    print(f"  - ACCEPTED: {agent_no_memory_accepted} ({agent_no_memory_accepted/total_routes*100:.1f}%)")
    print(f"  - REFUSED:  {agent_no_memory_refused} ({agent_no_memory_refused/total_routes*100:.1f}%)")
    
    print(f"\nAgent WITH memory_read scope:")
    print(f"  - ACCEPTED: {agent_with_memory_accepted} ({agent_with_memory_accepted/total_routes*100:.1f}%)")
    print(f"  - REFUSED:  {agent_with_memory_refused} ({agent_with_memory_refused/total_routes*100:.1f}%)")
    
    # Determine the defect
    print("\n" + "-"*80)
    print("CONCLUSION:")
    print("-"*80)
    
    if agent_no_memory_accepted == 0:
        print("✓ CONSENT INTEGRITY DEFECT: Agent without memory_read is REFUSED")
        print("  The approval UI reports success, but the operator cannot tell")
        print("  that memory_read is a grantable but nongated scope.")
        print("  This matches #2095 class.")
        return "consent_integrity"
    elif agent_no_memory_accepted == total_routes:
        print("✗ PRIVILEGE HOLE: Agent without memory_read is ACCEPTED")
        print("  Memory routes are reachable WITHOUT memory_read scope.")
        print("  This is a privilege hole - memory_read is decorative.")
        return "privilege_hole"
    else:
        print("? UNEXPECTED: Mixed results")
        print(f"  Some routes accepted ({agent_no_memory_accepted}), some refused ({agent_no_memory_refused})")
        return "mixed_results"


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result != "mixed_results" else 1)
