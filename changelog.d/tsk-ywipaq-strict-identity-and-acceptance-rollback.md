### Fixed
- Strict identity on project_create now requires a valid registry token; no-token requests with a registered handle return 401 instead of being attributed to that handle (CWE-287).
- Failed acceptance writes now roll back the project and revoke the project_tasks grant instead of leaving them live.
