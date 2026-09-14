#!/usr/bin/env python3
"""
Quick test to understand the current state of memory route authorization.
"""

import asyncio
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, '/tmp/exec-tsk-zndqmm')

from fastapi import FastAPI
from tinyagentos.agent_registry_store import AgentRegistryStore, load_or_create_signing_keypair, mint_registry_token
from tinyagentos.agent_grants_store import AgentGrantsStore

async def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Setup app
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
        
        # Check which routes exist
        from tinyagentos.routes.memory import router as memory_router
        from tinyagentos.routes.memory_management import router as memory_mgmt_router
        from tinyagentos.routes.user_memory import router as user_memory_router
        
        print("Checking which routes have scope checks...")
        
        # Check memory.py routes
        print("\n=== memory.py routes ===")
        for route in memory_router.routes:
            print(f"{route.path} {route.name}")
            
        # Check memory_management.py routes
        print("\n=== memory_management.py routes ===")
        for route in memory_mgmt_router.routes:
            print(f"{route.path} {route.name}")
            
        # Check user_memory.py routes
        print("\n=== user_memory.py routes ===")
        for route in user_memory_router.routes:
            print(f"{route.path} {route.name}")
            
        # Check for scope checks in the routes
        print("\n=== Checking for scope checks ===")
        
        # Look at memory.py source
        print("\nLooking at memory.py...")
        import inspect
        with open('/tmp/exec-tsk-zndqmm/tinyagentos/routes/memory.py', 'r') as f:
            content = f.read()
            
        # Check for check_agent_scope usage
        if 'check_agent_scope' in content:
            print("  ✓ check_agent_scope found in memory.py")
        else:
            print("  ✗ check_agent_scope NOT found in memory.py")
            
        # Check memory_management.py
        print("\nLooking at memory_management.py...")
        with open('/tmp/exec-tsk-zndqmm/tinyagentos/routes/memory_management.py', 'r') as f:
            content = f.read()
            
        if 'check_agent_scope' in content:
            print("  ✓ check_agent_scope found in memory_management.py")
        else:
            print("  ✗ check_agent_scope NOT found in memory_management.py")
            
        # Check user_memory.py
        print("\nLooking at user_memory.py...")
        with open('/tmp/exec-tsk-zndqmm/tinyagentos/routes/user_memory.py', 'r') as f:
            content = f.read()
            
        if 'check_agent_scope' in content:
            print("  ✓ check_agent_scope found in user_memory.py")
        else:
            print("  ✗ check_agent_scope NOT found in user_memory.py")
            
        print("\n=== Current state ===")
        print("The issue is that memory routes don't have scope checks.")
        print("We need to add scope checks to all memory routes:")
        print("1. memory_read scope for read operations")
        print("2. memory_write scope for write operations")
        print("3. tools_execute scope for tools execution")

if __name__ == "__main__":
    asyncio.run(main())
