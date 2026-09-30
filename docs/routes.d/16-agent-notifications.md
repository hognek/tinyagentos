# Agent notification posting (`notifications_write` grant)

<!-- Route module `tinyagentos/routes/notifications.py`, scope `notifications_write`. Dual-auth: human session stays admin-only; agent bearer reaches the same handler with grant verification -->

## `POST /api/notifications`

Body:
```json
{
  "title": "string (required, max 120 chars)",
  "message": "string (required, max 1000 chars)",
  "level": "info | warning",
  "source": "ignored on agent path",
  "data": {
    "project_id": "string (optional, per-project grant target)"
  }
}
```

## Agent path (registry JWT with `notifications_write` grant)

- Middleware admits exactly `POST /api/notifications` for agent registry bearers. `GET` and mark-read routes stay session-only.
- The route verifies the JWT + grant + project binding via `check_agent_scope_for_project`.
- A global (null-project) grant posts to instance admin(s). A per-project grant posts to that project's owner only. The agent never chooses the recipient.
- `source` comes from the grant, NOT the body: the store row always shows `agent:<canonical_id>`. The body's `source` is ignored.
- `data.from_agent` is stamped to the agent's canonical_id.
- Level: agents may post `info` or `warning` only. `error` is refused with 400.
- Caps: `title` <= 120 chars, `message` <= 1000 chars, `data` <= 4 KB serialized. Violations return 422.
- Rate limit: 10 posts per 10 minutes per canonical_id. Exceeding returns 429 `{"error": "rate_limited", "retry_after": N}`.
- Delivery goes through the same `store.add` path as the human path, so SSE and web-push fire.

## Human path (session / local token)

Unchanged: `_require_admin` gate, any valid level, source from body.

## Response

```json
{"ok": true}
```

## Live update

The notification is inserted through `NotificationStore.add`, which fans out to the event bus for SSE and dispatches web-push to the recipient's subscriptions.
