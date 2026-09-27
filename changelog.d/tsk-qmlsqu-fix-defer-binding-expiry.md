### Fixed

- **auth-requests.py:1019-1105** - Fix for deferred grant expiry inheritance issue:
  - When an agent with a deferred grant (project_id=None) is assigned to a project, the project-bound grant now correctly inherits the expires_at from the deferred grant
  - If the deferred grant has expired, the binding is refused with a 400 error (no grant row written)
  - When both a deferred grant with expiry and a request with expiry exist, the earlier bound is kept (never lengthened)
  - Deferred grants without expiry still bind to unbounded project-bound grants (unbounded unchanged behavior)
