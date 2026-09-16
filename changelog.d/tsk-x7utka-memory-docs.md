### Fixed

- Removed `memory_read`, `memory_write` and `tools_execute` from documentation scope offers. These scopes were removed from the grantable vocabulary as no route enforces them and agent tokens are refused on `/api/memory/*` and `/api/user-memory/*` by auth_middleware.