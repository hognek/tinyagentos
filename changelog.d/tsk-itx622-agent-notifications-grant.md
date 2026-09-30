### Added
- Agents holding an approved `notifications_write` grant can now POST `/api/notifications` through the normal store path. Global grants deliver to instance admins; per-project grants deliver to that project's owner. The agent's canonical_id is forced as the source and cannot be spoofed.

### Security
- Agent notification posts are capped at `info`/`warning` level only (refused with 400 for `error`), with body limits of 120-char title, 1000-char message, and 4 KB serialized data (422 over). A per-canonical_id rate limit of 10 per 10 minutes returns 429 `{"error": "rate_limited", "retry_after": N}`.
