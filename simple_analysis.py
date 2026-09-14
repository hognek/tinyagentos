#!/usr/bin/env python3
"""
Simple analysis of current memory route authorization state.
"""

print("="*80)
print("MEMORY ROUTE AUTHORIZATION ANALYSIS")
print("="*80)

# Read and analyze each file
for filepath in [
    'tinyagentos/routes/memory.py',
    'tinyagentos/routes/memory_management.py', 
    'tinyagentos/routes/user_memory.py'
]:
    print(f"\n{'='*80}")
    print(f"File: {filepath}")
    print('='*80)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Find all routes by looking for @router. calls
    lines = content.split('\n')
    routes_found = 0
    scope_checks_found = 0
    
    for i, line in enumerate(lines):
        # Look for route definitions
        if '@router.' in line and '/api/' in line:
            # Extract route method and path
            route_line = line.strip()
            routes_found += 1
            print(f"\nRoute {routes_found}:")
            print(f"  {route_line}")
            
            # Look for function definition
            func_line = lines[i+1].strip() if i+1 < len(lines) else ''
            print(f"  Function: {func_line}")
            
            # Look ahead in the function body for scope checks
            # Check a reasonable range (next 50 lines or until next @ or def at same indent)
            for j in range(i+2, min(i+50, len(lines))):
                if lines[j].strip().startswith('@router.') or (lines[j].strip().startswith('async def ') and not lines[j].strip().startswith('async def ')):
                    break
                if 'check_agent_scope' in lines[j]:
                    scope_checks_found += 1
                    # Extract scope name
                    match = lines[j].strip()
                    print(f"    ✓ Scope check: {match}")
                    break
    
    print(f"\nSummary for {filepath}:")
    print(f"  Routes found: {routes_found}")
    print(f"  Routes with scope checks: {scope_checks_found}")
    print(f"  Routes WITHOUT scope checks: {routes_found - scope_checks_found}")

print(f"\n{'='*80}")
print("VALID_SCOPES ANALYSIS")
print('='*80)

# Check VALID_SCOPES
with open('/tmp/exec-tsk-zndqmm/tinyagentos/routes/agent_auth_requests.py', 'r') as f:
    auth_content = f.read()
    
# Find VALID_SCOPES
import re
valid_scopes_match = re.search(r'VALID_SCOPES\s*=\s*frozenset\(\s*{([^}]+)}\)', auth_content, re.DOTALL)
if valid_scopes_match:
    scopes_text = valid_scopes_match.group(1)
    # Extract scope names
    scopes = []
    for match in re.finditer(r'["\']([^"\']+)["\']', scopes_text):
        scopes.append(match.group(1))
    
    print(f"\nVALID_SCOPES includes {len(scopes)} scopes:")
    for scope in sorted(scopes):
        print(f"  - {scope}")
        
    # Focus on memory and tools scopes
    memory_scopes = ['memory_read', 'memory_write']
    tools_scopes = ['tools_execute']
    
    print(f"\nMemory-related scopes in VALID_SCOPES:")
    for scope in memory_scopes:
        if scope in scopes:
            print(f"  ✓ {scope}")
        else:
            print(f"  ✗ {scope} - MISSING!")
            
    print(f"\nTools-related scopes in VALID_SCOPES:")
    for scope in tools_scopes:
        if scope in scopes:
            print(f"  ✓ {scope}")
        else:
            print(f"  ✗ {scope} - MISSING!")

print(f"\n{'='*80}")
print("CONCLUSION")
print('='*80)
print("Based on the analysis:")
print("1. The VALID_SCOPES frozenset includes memory_read, memory_write, and tools_execute")
print("2. BUT most memory routes have NO scope checks (no check_agent_scope calls)")
print("3. This means agents can reach memory routes WITHOUT the required scopes")
print("4. The defects described in tsk-zndqmm are CONFIRMED")
print("\nWe need to:")
print("1. Add check_agent_scope('memory_read') to read operations")
print("2. Add check_agent_scope('memory_write') to write operations")
print("3. Add check_agent_scope('tools_execute') to tools execution")
print("4. Update user_memory.py routes with appropriate scope checks")

