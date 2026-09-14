#!/usr/bin/env python3
"""
Check the actual current state of the files on disk.
"""

import re

def check_file(filepath, filename):
    print(f"\n{'='*80}")
    print(f"Checking: {filename}")
    print('='*80)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Find routes and check for scope checks
    lines = content.split('\n')
    
    print("\nRoute definitions and scope checks:")
    
    for i, line in enumerate(lines):
        if '@router.' in line and '/api/' in line:
            # Extract route
            route_info = line.strip()
            # Get function name
            if i+1 < len(lines):
                func_line = lines[i+1].strip()
                # Look ahead for scope check
                scope_found = False
                scope_type = None
                
                for j in range(i+1, min(i+30, len(lines))):
                    if 'check_agent_scope' in lines[j]:
                        scope_found = True
                        # Extract scope type
                        match = re.search(r'check_agent_scope\s*\(\s*request\s*,\s*["\'](\w+)["\']', lines[j])
                        if match:
                            scope_type = match.group(1)
                        break
                
                status = "✓" if scope_found else "✗"
                scope_str = f"[{scope_type}]" if scope_type else ""
                
                print(f"  {status} {route_info} -> {func_line} {scope_str}")

# Check each file
check_file('tinyagentos/routes/memory.py', 'memory.py')
check_file('tinyagentos/routes/memory_management.py', 'memory_management.py')
check_file('tinyagentos/routes/user_memory.py', 'user_memory.py')

print(f"\n{'='*80}")
print("SUMMARY OF WHAT NEEDS TO BE FIXED")
print('='*80)
print("\nBased on the analysis, we need to add scope checks to:")
print("\n1. tinyagentos/routes/memory.py:")
print("   - memory_collections: Add check_agent_scope('memory_read')")
print("   - memory_delete_chunk: Add check_agent_scope('memory_write')")
print("\n2. tinyagentos/routes/memory_management.py:")
print("   - memory_settings_put: Add check_agent_scope('memory_write')")
print("   - memory_backend_capabilities: Add check_agent_scope('memory_read')")
print("   - memory_backend_settings_schema: Add check_agent_scope('memory_read')")
print("   - agent_memory_config_get: Add check_agent_scope('memory_read')")
print("   - agent_memory_config_put: Add check_agent_scope('memory_write')")
print("   - All recipe routes: Add check_agent_scope('memory_write') for write ops")
print("\n3. tinyagentos/routes/user_memory.py:")
print("   ALL routes need appropriate scope checks:")
print("   - get_stats: check_agent_scope('memory_read')")
print("   - get_settings: check_agent_scope('memory_read')")
print("   - update_settings: check_agent_scope('memory_write')")
print("   - search: check_agent_scope('memory_read')")
print("   - agent_search: check_agent_scope('memory_read')")
print("   - browse: check_agent_scope('memory_read')")
print("   - save: check_agent_scope('memory_write')")
print("   - delete_chunk: check_agent_scope('memory_write')")
print("   - list_collections: check_agent_scope('memory_read')")
print("   - migrate_to_taosmd: check_agent_scope('memory_write')")

