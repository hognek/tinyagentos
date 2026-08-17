### Fixed
- `POST /api/notifications` now rejects unknown `level` values with a 400 error, matching the canonical level set `{"info", "success", "warning", "error"}` (single source of truth: `VALID_LEVELS` in `tinyagentos/notifications.py`, shared with the `notify_user` tool).
