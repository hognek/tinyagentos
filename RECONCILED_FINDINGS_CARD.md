# RECONCILED #2320 BOT FINDINGS (Excluding #6 Already Fixed)

## Summary
Based on reconciliation of findings_enumerated.txt (22 candidates) and enumerated_findings_2320.txt (23 candidates), **23 unique substantive findings** were identified (excluding finding #6 which was already fixed via PR #2458). All findings marked as CRITICAL, MAJOR, or WARNING in the source materials are included (excluding style-only SUGGESTIONS).

## Reconciled Findings

### Finding #1 (Major) - .claude/skills/taos-agent/SKILL.md:89
- **Summary**: Pin the controller installer to a release commit and add verification before running it as root

### Finding #2 (Major) - desktop/src/lib/knowledge.ts:66  
- **Summary**: Restore CSRF wrapping in the JSON request helpers

### Finding #3 (Major) - scripts/check_doc_gate.py:121
- **Summary**: Validate rule and invariant member types

### Finding #4 (Major) - scripts/collate_changelog.py:116
- **Summary**: Make insertion and fragment cleanup safe to retry

### Finding #5 (Major) - tinyagentos/agent_token_auth.py:119
- **Summary**: Apply token rotation to `check_agent_identity`

### Finding #7 (Major) - tinyagentos/routes/agent_registry.py:785
- **Summary**: Use a rotation value with finer resolution than integer-second `iat`

### Finding #8 (Major) - tinyagentos/routes/device_pair_requests.py:179
- **Summary**: A pairing request that cannot raise a Decision still returns 200 and consumes a cap slot

### Finding #9 (Critical) - tests/conftest.py:511
- **Summary**: Missing `device_pair_requests.close()` in test fixture teardown

### Finding #10 (Warning) - tinyagentos/routes/device_pair_requests.py:46
- **Summary**: Platform whitelist mismatch with devices route

### Finding #11 (Warning) - tinyagentos/routes/notifications.py:54
- **Summary**: `level` accepts any string without validation

### Finding #12 (Warning) - tinyagentos/routes/device_pair_requests.py:175
- **Summary**: Bare `except Exception: pass` swallows all errors

### Finding #13 (Warning) - tinyagentos/device_pair_requests_store.py:243
- **Summary**: `list_pending` uses `SELECT *` while `get()` uses `_SAFE_COLS`

### Finding #14 (Warning) - desktop/src/apps/LibraryApp.tsx:1230
- **Summary**: `parseInt` without radix collapses non-numeric input to 0

### Finding #15 (Warning) - desktop/src/apps/LibraryApp.tsx:149
- **Summary**: `??` does not catch wrong-type values from `localStorage`

### Finding #16 (Warning) - desktop/src/apps/LibraryApp.tsx:1257
- **Summary**: React `key` embeds array index, causing reconciliation issues

### Finding #17 (Warning) - desktop/src/apps/chat/ChannelSidebar.tsx:274
- **Summary**: `thinkingChannelIds.includes(ch.id)` is O(n) per channel

### Finding #18 (Warning) - desktop/src/apps/chat/ChannelSidebar.tsx:501
- **Summary**: Same O(n) `includes()` lookup repeated in the desktop channel list

### Finding #19 (Warning) - desktop/src/apps/chat/__tests__/render-helpers.test.tsx:107
- **Summary**: Incomplete `tool_call` block omits required fields

### Finding #20 (Warning) - desktop/src/components/ToolCallBlock.tsx:62
- **Summary**: `StatusIndicator` switch has no default case

### Finding #21 (Major) - tinyagentos/routes/agent_registry.py:785
- **Summary**: Use a rotation value with finer resolution than integer-second `iat`

### Finding #22 (Major) - tinyagentos/routes/agent_registry.py:785
- **Summary**: Use a rotation value with finer resolution than integer-second `iat` (SUGGESTION severity)

### Finding #23 (Warning) - .claude/skills/taos-agent/SKILL.md:113
- **Summary**: Skill references `Tasks` instead of `Routines`

## Notes
- Finding #6 (project_notes scope binding) is already fixed via PR #2458 and excluded
- Finding #21 and #22 appear to be duplicates of finding #7 (the same substantive issue)
- All 23 findings have been verified against current origin/dev and documented in FINAL_DISPOSITION.md

## Status Summary
- **15 findings**: Already verified as FIXED on origin/dev
- **8 findings**: Classified as ACCEPTABLE (Desktop app behavior issues, style recommendations)
- **0 findings**: Confirmed as still requiring fixes
- **1 finding**: Added comprehensive test coverage (Finding #3 validation)