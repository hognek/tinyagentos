## RECONCILED FINDING LIST: #2320 BOT FINDINGS (excluding #6 already fixed)

From the bot-review retrospective audit — 2026-08-16 and the enumerated findings from the durable source, here are the **22 remaining #2320 bot findings** (excluding finding #6 which is already fixed via PR #2458):

---

1. **Finding #1** (Critical) - .claude/skills/taos-agent/SKILL.md:89
   - Summary: - Summary: Pin the controller installer to a release commit and add verification before running it as root

2. **Finding #2** (Major) - desktop/src/lib/knowledge.ts:66
   - Summary: - Summary: Restore CSRF wrapping in the JSON request helpers

3. **Finding #3** (Major) - scripts/check_doc_gate.py:121
   - Summary: - Summary: Validate rule and invariant member types

4. **Finding #4** (Major) - scripts/collate_changelog.py:116
   - Summary: - Summary: Make insertion and fragment cleanup safe to retry

5. **Finding #5** (Major) - tinyagentos/agent_token_auth.py:119
   - Summary: - Summary: Apply token rotation to `check_agent_identity`

6. **Finding #7** (Major) - tinyagentos/routes/agent_registry.py:785
   - Summary: - Summary: Use a rotation value with finer resolution than integer-second `iat`

7. **Finding #8** (Major) - tinyagentos/routes/device_pair_requests.py:179
   - Summary: - Summary: A pairing request that cannot raise a Decision still returns 200 and consumes a cap slot

8. **Finding #9** (Critical) - tests/conftest.py:511
   - Summary: - Summary: Missing `device_pair_requests.close()` in test fixture teardown

9. **Finding #10** (Warning) - tinyagentos/routes/device_pair_requests.py:46
   - Summary: - Summary: Platform whitelist mismatch with devices route

10. **Finding #11** (Warning) - tinyagentos/routes/notifications.py:54
   - Summary: - Summary: `level` accepts any string without validation

11. **Finding #12** (Warning) - tinyagentos/routes/device_pair_requests.py:175
   - Summary: - Summary: Bare `except Exception: pass` swallows all errors

12. **Finding #13** (Warning) - tinyagentos/device_pair_requests_store.py:243
   - Summary: - Summary: `list_pending` uses `SELECT *` while `get()` uses `_SAFE_COLS`

13. **Finding #14** (Warning) - desktop/src/apps/LibraryApp.tsx:1230
   - Summary: - Summary: `parseInt` without radix collapses non-numeric input to 0

14. **Finding #15** (Warning) - desktop/src/apps/LibraryApp.tsx:149
   - Summary: - Summary: `??` does not catch wrong-type values from `localStorage`

15. **Finding #16** (Warning) - desktop/src/apps/LibraryApp.tsx:1257
   - Summary: - Summary: React `key` embeds array index, causing reconciliation issues

16. **Finding #17** (Suggestion) - desktop/src/apps/chat/ChannelSidebar.tsx:274
   - Summary: - Summary: `thinkingChannelIds.includes(ch.id)` is O(n) per channel

17. **Finding #18** (Suggestion) - desktop/src/apps/chat/ChannelSidebar.tsx:501
   - Summary: - Summary: Same O(n) `includes()` lookup repeated in the desktop channel list

18. **Finding #19** (Warning) - desktop/src/apps/chat/__tests__/render-helpers.test.tsx:107
   - Summary: - Summary: Incomplete `tool_call` block omits required fields

19. **Finding #20** (Warning) - desktop/src/components/ToolCallBlock.tsx:62
   - Summary: - Summary: `StatusIndicator` switch has no default case

20. **Finding #21** (Critical) - tinyagentos/routes/agent_registry.py:785
   - Summary: - Summary: CRITICAL - Use a rotation value with finer resolution than integer-second `iat`

21. **Finding #22** (Suggestion) - tinyagentos/routes/agent_registry.py:785
   - Summary: - Summary: SUGGESTION - Use a rotation value with finer resolution than integer-second `iat`

22. **Finding #23** (Warning) - .claude/skills/taos-agent/SKILL.md:113
   - Summary: - Summary: WARNING - Skill references `Tasks` instead of `Routines`

**Note:** Finding #6 (project_notes scope binding) is already fixed via PR #2458 and should be excluded from this verification and fix process.

Next Steps:
1. Each finding needs to be verified against current origin/dev
2. Confirmed findings will require test reproduction before fixing
3. Stale findings will be noted as evidence that they're already fixed
4. PR size constraint: max 7 findings per PR if more than 7 are confirmed
