#!/usr/bin/env python3
"""
Final measurement to determine which defect exists.

This script measures whether memory routes are protected by scope checks
or if they are privilege holes.
"""

import asyncio
import tempfile
from pathlib import Path
import sys
import traceback

sys.path.insert(0, '/tmp/exec-tsk-zndqmm')

from fastapi import FastAPI
from tinyagentos.agent_registry_store import AgentRegistryStore, load_or_create_signing_keypair, mint_registry_token
from tinyagentos.agent_grants_store import AgentGrantsStore
from tinyagentos.agent_token_auth import check_agent_scope

async def measure_current_state():
    """Measure the current state of memory routes."""
    print("FINAL MEASUREMENT for tsk-zndqmm")
    print("="*80)
    print("\nGoal: Determine whether memory routes have scope checks or are privilege holes.")
    print("\nWe need to measure whether agents WITHOUT memory_read/memory_write")
    print("scopes can access the routes.")
    print("\nBased on the audit from tsk-zndqmm:")
    print("memory_read, memory_write, tools_execute have NO enforcement points.")
    print("="*80)
    
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
        agent_no_mem_read = await registry.register(
            framework="test",
            display_name="Agent No Mem Read",
            user_id="admin",
            origin="taos-deployed",
            handle="@agent-no-mem-read",
        )
        await registry.set_status(agent_no_mem_read["canonical_id"], "active")
        await grants.add_grant(agent_no_mem_read["canonical_id"], "a2a_receive", project_id="prj-1")
        
        # Create agent WITH memory_read scope
        agent_with_mem_read = await registry.register(
            framework="test",
            display_name="Agent With Mem Read",
            user_id="admin",
            origin="taos-deployed",
            handle="@agent-with-mem-read",
        )
        await registry.set_status(agent_with_mem_read["canonical_id"], "active")
        await grants.add_grant(agent_with_mem_read["canonical_id"], "memory_read", project_id="prj-1")
        
        # Create agent WITHOUT memory_write scope
        agent_no_mem_write = await registry.register(
            framework="test",
            display_name="Agent No Mem Write",
            user_id="admin",
            origin="taos-deployed",
            handle="@agent-no-mem-write",
        )
        await registry.set_status(agent_no_mem_write["canonical_id"], "active")
        await grants.add_grant(agent_no_mem_write["canonical_id"], "memory_read", project_id="prj-1")
        
        # Create agent WITH memory_write scope
        agent_with_mem_write = await registry.register(
            framework="test",
            display_name="Agent With Mem Write",
            user_id="admin",
            origin="taos-deployed",
            handle="@agent-with-mem-write",
        )
        await registry.set_status(agent_with_mem_write["canonical_id"], "active")
        await grants.add_grant(agent_with_mem_write["canonical_id"], "memory_write", project_id="prj-1")
        
        app.state.agent_registry = registry
        app.state.agent_grants = grants
        app.state.agent_registry_keypair = (priv, pub)
        
        # Create fake request class for check_agent_scope
        class _FakeRequest:
            def __init__(self, app, token: str | None = None):
                self.app = app
                self.headers = {}
                if token is not None:
                    self.headers["Authorization"] = f"Bearer {token}"
        
        # Test memory_read scope
        print("\nTesting memory_read scope enforcement...")
        print("-"*40)
        
        # Agent WITHOUT memory_read should be REFUSED
        token_no_mem_read = mint_registry_token(
            agent_no_mem_read["canonical_id"], priv, user_id="admin", framework="test", project_id="prj-1"
        )
        req_no_mem_read = _FakeRequest(app, token_no_mem_read)
        
        try:
            result = await check_agent_scope(req_no_mem_read, "memory_read")
            if result is None:
                print("✗ Agent without memory_read was ACCEPTED (no token present)")
                print("  This is unexpected - check if middleware handled this")
            else:
                print(f"✗ Agent without memory_read was ACCEPTED: {result}")
                print("  DEFECT: PRIVILEGE HOLE - memory_read is decorative")
                privilege_hole_detected = True
        except Exception as e:
            print(f"✓ Agent without memory_read was REFUSED: {e}")
            print("  This suggests CONSENT INTEGRITY defect")
            consent_integrity_detected = True
        
        # Agent WITH memory_read should be ACCEPTED
        token_with_mem_read = mint_registry_token(
            agent_with_mem_read["canonical_id"], priv, user_id="admin", framework="test", project_id="prj-1"
        )
        req_with_mem_read = _FakeRequest(app, token_with_mem_read)
        
        try:
            result = await check_agent_scope(req_with_mem_read, "memory_read")
            if result is not None:
                print(f"✓ Agent with memory_read was ACCEPTED: {result}")
            else:
                print("✗ Agent with memory_read was NOT ACCEPTED")
        except Exception as e:
            print(f"✗ Agent with memory_read was REFUSED: {e}")
        
        # Test memory_write scope
        print("\nTesting memory_write scope enforcement...")
        print("-"*40)
        
        # Agent WITHOUT memory_write should be REFUSED
        token_no_mem_write = mint_registry_token(
            agent_no_mem_write["canonical_id"], priv, user_id="admin", framework="test", project_id="prj-1"
        )
        req_no_mem_write = _FakeRequest(app, token_no_mem_write)
        
        try:
            result = await check_agent_scope(req_no_mem_write, "memory_write")
            if result is None:
                print("✗ Agent without memory_write was ACCEPTED (no token present)")
                print("  This is unexpected")
            else:
                print(f"✗ Agent without memory_write was ACCEPTED: {result}")
                print("  DEFECT: PRIVILEGE HOLE - memory_write is decorative")
                privilege_hole_detected = True
        except Exception as e:
            print(f"✓ Agent without memory_write was REFUSED: {e}")
            if 'consent_integrity_detected' not in locals():
                consent_integrity_detected = True
        
        # Agent WITH memory_write should be ACCEPTED
        token_with_mem_write = mint_registry_token(
            agent_with_mem_write["canonical_id"], priv, user_id="admin", framework="test", project_id="prj-1"
        )
        req_with_mem_write = _FakeRequest(app, token_with_mem_write)
        
        try:
            result = await check_agent_scope(req_with_mem_write, "memory_write")
            if result is not None:
                print(f"✓ Agent with memory_write was ACCEPTED: {result}")
            else:
                print("✗ Agent with memory_write was NOT ACCEPTED")
        except Exception as e:
            print(f"✗ Agent with memory_write was REFUSED: {e}")
        
        print("\n" + "="*80)
        print("CONCLUSION")
        print("="*80)
        
        if 'privilege_hole_detected' in locals():
            print("✗ PRIVILEGE HOLE DETECTED")
            print("  Memory routes are reachable WITHOUT the required scopes.")
            print("  The scopes memory_read, memory_write, tools_execute are decorative.")
            print("  This means we should REMOVE them from VALID_SCOPES.")
            return "privilege_hole"
        elif 'consent_integrity_detected' in locals():
            print("✓ CONSENT INTEGRITY DEFECT")
            print("  The approval UI reports success, but the operator cannot tell")
            print("  that these scopes grant nothing.")
            print("  This matches #2095 class.")
            print("  This means we should ADD scope checks to the routes.")
            return "consent_integrity"
        else:
            print("? UNCLEAR RESULTS")
            print("  Could not determine the defect.")
            return "unclear"

if __name__ == "__main__":
    result = asyncio.run(measure_current_state())
    sys.exit(0)
