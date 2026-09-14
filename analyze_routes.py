#!/usr/bin/env python3
"""
Analyze all memory and user-memory routes to understand current authorization state.
"""

import re

# Files to analyze
files_to_check = [
    ('tinyagentos/routes/memory.py', 'memory.py'),
    ('tinyagentos/routes/memory_management.py', 'memory_management.py'),
    ('tinyagentos/routes/user_memory.py', 'user_memory.py'),
]

# Patterns for scope checks
scope_check_pattern = r'check_agent_scope\s*\(\s*request\s*,\s*["\'](\w+)["\']'

print("="*80)
print("ANALYSIS: Memory Route Authorization State")
print("="*80)

total_routes = 0
scope_checked_routes = 0

for filepath, filename in files_to_check:
    print(f"\n{'='*80}")
    print(f"Analyzing {filename}")
    print('='*80)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Find all route definitions
    route_pattern = r'@router\.(\w+)\s*\(\s*["\']/api/(\w+)["\']'
    routes = re.findall(route_pattern, content)
    
    print(f"\nFound {len(routes)} routes:")
    
    for method, path in routes:
        print(f"  {method.upper()} /api/{path}")
        total_routes += 1
        
        # Extract the full route line (simplified)
        route_line_pattern = rf'@router\.{method}\s*\(\s*["\']/api/{path}["\']'
        route_match = re.search(route_line_pattern, content)
        if route_match:
            route_start = route_match.start()
            # Get the function definition (next def or @ after route)
            line_start = content.find('\n', route_start) + 1
            if line_start < len(content):
                next_def = content.find('\nasync def ', line_start)
                next_at = content.find('\n@', line_start)
                next_end = min([pos for pos in [next_def, next_at, len(content)] if pos > line_start])
                route_func = content[line_start:next_end].strip()
                
                # Check for scope check
                scope_match = re.search(scope_check_pattern, route_func)
                if scope_match:
                    scope_checked_routes += 1
                    print(f"    ✓ Has scope check: {scope_match.group(1)}")
                else:
                    print(f"    ✗ NO scope check")

print(f"\n{'='*80}")
print("SUMMARY")
print('='*80)
print(f"Total routes analyzed: {total_routes}")
print(f"Routes with scope checks: {scope_checked_routes}")
print(f"Routes WITHOUT scope checks: {total_routes - scope_checked_routes}")
print(f"Percentage with scope checks: {scope_checked_routes/total_routes*100:.1f}%")

# Additional analysis: check VALID_SCOPES
print("\n{'='*80}")
print("VALID_SCOPES analysis")
print('='*80)

with open('/tmp/exec-tsk-zndqmm/tinyagentos/routes/agent_auth_requests.py', 'r') as f:
    auth_content = f.read()

valid_scopes_match = re.search(r'VALID_SCOPES\s*=\s*frozenset\(\s*{([^}]+)}\)', auth_content, re.DOTALL)
if valid_scopes_match:
    scopes_text = valid_scopes_match.group(1)
    scopes = [s.strip().strip('"\' ') for s in re.findall(r'["\']([^"\']+)["\']', scopes_text)]
    
    print(f"VALID_SCOPES includes {len(scopes)} scopes:")
    for scope in sorted(scopes):
        print(f"  - {scope}")
        
    # Check which scopes have enforcement points
    memory_scopes = ['memory_read', 'memory_write']
    print(f"\nMemory-related scopes:")
    for scope in memory_scopes:
        if scope in scopes:
            print(f"  ✓ {scope} is in VALID_SCOPES")
        else:
            print(f"  ✗ {scope} is NOT in VALID_SCOPES")

