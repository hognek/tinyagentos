#!/usr/bin/env python3
"""
Direct measurement of the memory scope defect as requested in tsk-zndqmm.

This script measures whether agents can reach /api/memory/* and /api/user-memory/*
at all, and whether the lack of scope enforcement means:
- CONSENT INTEGRITY: tokens without memory_read are REFUSED by auth_middleware
- PRIVILEGE HOLE: tokens without memory_read are ACCEPTED (memory is reachable)

We measure the REFUSING direction explicitly: a token WITHOUT memory_read
must be shown to be refused, not merely a token with it shown to succeed.
"""

import asyncio
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, '/tmp/exec-tsk-zndqmm')

from fastapi import FastAPI, HTTPException
from tinyagentos.agent_registry_store import (
    AgentRegistryStore, 
    load_or_create_signing_keypair,
    mint_registry_token
)
from tinyagentos.agent_grants_store import AgentGrantsStore
from tinyagentos.agent_token_auth import check_agent_scope
from tinyagentos.auth_middleware import AuthMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
import json


class _FakeRequest:
    """Minimal stand-in for a starlette Request."""
    
    def __init__(self, app, token: str | None = None):
        self.app = app
        self.headers = {}
        if token is not None:
            self.headers["Authorization"] = f"Bearer {token}"


async def _setup_test_app(tmp_path):
    """Create a test app with fresh stores."""
    from fastapi import FastAPI
    from tinyagentos.agent_registry_store import AgentRegistryStore
    from tinyagentos.agent_grants_store import AgentGrantsStore
    from tinyagentos.agent_registry_store import load_or_create_signing_keypair
    
    app = FastAPI()
    
    # Setup stores
    registry = AgentRegistryStore(tmp_path / "reg.db")
    grants = AgentGrantsStore(tmp_path / "grants.db")
    await registry.init()
    await grants.init()
    
    priv, pub = load_or_create_signing_keypair(tmp_path / "keys")
    
    # Create agent WITHOUT memory_read scope
    agent_no_mem = await registry.register(
        framework="test",
        display_name="Agent No Mem",
        user_id="admin",
        origin="taos-deployed",
        handle="@agent-no-mem",
    )
    await registry.set_status(agent_no_mem["canonical_id"], "active")
    await grants.add_grant(agent_no_mem["canonical_id"], "a2a_receive", project_id="prj-1")
    
    # Create agent WITH memory_read scope
    agent_with_mem = await registry.register(
        framework="test",
        display_name="Agent With Mem",
        user_id="admin",
        origin="taos-deployed",
        handle="@agent-with-mem",
    )
    await registry.set_status(agent_with_mem["canonical_id"], "active")
    await grants.add_grant(agent_with_mem["canonical_id"], "memory_read", project_id="prj-1")
    
    app.state.agent_registry = registry
    app.state.agent_grants = grants
    app.state.agent_registry_keypair = (priv, pub)
    
    return app, agent_no_mem, agent_with_mem


async def measure_defect():
    """Measure which defect exists."""
    print("MEASUREMENT PHASE for tsk-zndqmm")
    print("="*80)
    print("\nGoal: Determine whether /api/memory/* and /api/user-memory/* routes")
    print("are protected by memory_read scope checks.")
    print("\nWe will test:")
    print("1. An agent WITHOUT memory_read scope tries to use /api/memory/* routes")
    print("2. If the agent is REFUSED by auth middleware -> CONSENT INTEGRITY defect")
    print("3. If the agent is ACCEPTED -> PRIVILEGE HOLE defect")
    print("\nWe must measure the REFUSING direction explicitly:")
    print("A token WITHOUT memory_read must be shown to be refused.")
    print("="*80)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        app, agent_no_mem, agent_with_mem = await _setup_test_app(tmp_path)
        
        # Import routes - these currently have NO scope checks
        from tinyagentos.routes.memory import router as memory_router
        app.include_router(memory_router)
        
        from tinyagentos.routes.user_memory import router as user_memory_router  
        app.include_router(user_memory_router)
        
        from tinyagentos.routes.memory_management import router as memory_mgmt_router
        app.include_router(memory_mgmt_router)
        
        priv, _pub = app.state.agent_registry_keypair
        
        # Create tokens
        token_no_mem = mint_registry_token(
            agent_no_mem["canonical_id"], priv, user_id="admin", framework="test", project_id="prj-1"
        )
        token_with_mem = mint_registry_token(
            agent_with_mem["canonical_id"], priv, user_id="admin", framework="test", project_id="prj-1"
        )
        
        # Helper to test if a route is accessible without scope
        class TestRouteResult:
            def __init__(self, route_name, method, route_path, needs_memory_read):
                self.route_name = route_name
                self.method = method
                self.route_path = route_path
                self.needs_memory_read = needs_memory_read
                self.accessed_without_memory_read = False
                self.accessed_with_memory_read = False
                self.refused_without_memory_read = False
                self.refused_with_memory_read = False
        
        # Test routes that should require memory_read
        test_routes = [
            # (route_name, route_path, method)
            ("memory_browse", "/api/memory/browse", "GET", "memory_read"),
            ("memory_search", "/api/memory/search", "POST", "memory_read"),  
            ("memory_collections", "/api/memory/collections/test-agent", "GET", "memory_read"),
            ("memory_delete_chunk", "/api/memory/chunk/abc123", "DELETE", "memory_read"),
            ("memory_stats", "/api/memory/stats", "GET", "memory_read"),
            ("memory_settings_get", "/api/memory/settings", "GET", "memory_read"),
            ("memory_settings_put", "/api/memory/settings", "PUT", "memory_read"),
            ("memory_backend_capabilities", "/api/memory/backend/capabilities", "GET", "memory_read"),
            ("memory_backend_settings_schema", "/api/memory/backend/settings-schema", "GET", "memory_read"),
            ("memory_recipes_schema", "/api/memory/recipes/schema", "GET", "memory_read"),
            ("memory_recipes_list", "/api/memory/recipes", "GET", "memory_read"),
            ("memory_recipes_get", "/api/memory/recipes/default", "GET", "memory_read"),
            ("memory_recipes_apply", "/api/memory/recipes/default/apply", "POST", "memory_read"),
            ("memory_recipes_recommend", "/api/memory/recipes/recommend", "POST", "memory_read"),
            ("memory_recipes_create", "/api/memory/recipes", "POST", "memory_read"),
            ("agent_memory_config_get", "/api/agents/{name}/memory-config", "GET", "memory_read"),
            ("agent_memory_config_put", "/api/agents/{name}/memory-config", "PUT", "memory_read"),
            # User memory routes
            ("user_memory_stats", "/api/user-memory/stats", "GET", "memory_read"),
            ("user_memory_settings", "/api/user-memory/settings", "GET", "memory_read"),
            ("user_memory_settings_update", "/api/user-memory/settings", "PUT", "memory_read"),
            ("user_memory_search", "/api/user-memory/search", "GET", "memory_read"),
            ("user_memory_agent_search", "/api/user-memory/agent-search", "GET", "memory_read"),
            ("user_memory_browse", "/api/user-memory/browse", "GET", "memory_read"),
            ("user_memory_save", "/api/user-memory/save", "POST", "memory_write"),
            ("user_memory_delete_chunk", "/api/user-memory/chunk/abc123", "DELETE", "memory_write"),
            ("user_memory_collections", "/api/user-memory/collections", "GET", "memory_read"),
            ("user_memory_migrate", "/api/user-memory/migrate", "POST", "memory_write"),
            # Memory management routes
            ("memory_management_stats", "/api/memory/stats", "GET", "memory_read"),
            ("memory_management_settings", "/api/memory/settings", "GET", "memory_read"),
        ]
        
        # We need to actually test the routes - but we need the full app setup
        # with all dependencies. Let me try a simpler approach: test the routes directly
        # through the app.
        
        # Create test client
        client = TestClient(app)
        
        print("\nTesting routes with agent WITHOUT memory_read scope...")
        refused_count = 0
        accepted_count = 0
        unexpected_count = 0
        
        for route_name, route_path, method, expected_scope in test_routes:
            # Skip routes that require path parameters we don't have
            if "{name}" in route_path:
                continue
                
            try:
                if method == "GET":
                    response = client.get(route_path, headers={"Authorization": f"Bearer {token_no_mem}"})
                elif method == "POST":
                    response = client.post(route_path, headers={"Authorization": f"Bearer {token_no_mem}"}, json={})
                elif method == "PUT":
                    response = client.put(route_path, headers={"Authorization": f"Bearer {token_no_mem}"}, json={})
                elif method == "DELETE":
                    response = client.delete(route_path, headers={"Authorization": f"Bearer {token_no_mem}"})
                else:
                    continue
                    
                if response.status_code in (401, 403):
                    refused_count += 1
                    print(f"  ✓ {route_name}: REFUSED (status {response.status_code}) - GOOD")
                elif response.status_code == 200:
                    accepted_count += 1
                    print(f"  ✗ {route_name}: ACCEPTED (status 200) - PROBLEM!")
                else:
                    unexpected_count += 1
                    print(f"  ? {route_name}: Unexpected status {response.status_code}")
                    
            except Exception as e:
                print(f"  ? {route_name}: Exception: {e}")
                unexpected_count += 1
        
        print("\n" + "="*80)
        print("RESULTS:")
        print(f"  Routes REFUSED without memory_read: {refused_count}")
        print(f"  Routes ACCEPTED without memory_read: {accepted_count}")
        print(f"  Routes with unexpected status: {unexpected_count}")
        
        if refused_count == len(test_routes):
            print("\n✓ MEASUREMENT COMPLETE: All routes are REFUSED without memory_read")
            print("  DEFECT: CONSENT INTEGRITY")
            print("  This matches #2095 - scopes are grantable but ungated.")
            return "consent_integrity"
        elif accepted_count == len(test_routes):
            print("\n✗ MEASUREMENT COMPLETE: All routes are ACCEPTED without memory_read")
            print("  DEFECT: PRIVILEGE HOLE")
            print("  Memory routes are reachable WITHOUT memory_read scope.")
            return "privilege_hole"
        else:
            print(f"\n? MEASUREMENT INCOMPLETE: Mixed results ({refused_count} refused, {accepted_count} accepted)")
            return "mixed_results"


if __name__ == "__main__":
    result = asyncio.run(measure_defect())
    sys.exit(0)
