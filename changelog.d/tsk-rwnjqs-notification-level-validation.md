### Fixed
- `POST /api/notifications` now rejects unknown `level` values with a 400 error, matching the allowed set `{"info", "warning", "error"}`.
