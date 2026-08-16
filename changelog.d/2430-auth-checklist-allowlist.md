### Fixed
- The auth middleware's agent Bearer allowlist now covers `GET`/`POST /api/projects/{project_id}/tasks/{task_id}/checklist-items`, so a registry JWT reaches the handlers' `project_tasks_create` scope check instead of being refused 401 at the gate. Inert until the checklist routes (#2415) merge; DELETE and per-item subpaths stay session-only (#2430).
