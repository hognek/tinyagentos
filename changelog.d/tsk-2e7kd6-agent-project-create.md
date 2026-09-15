### Added

- Agents can request project creation via `POST /api/agents/auth-requests` with `kind: "project_create"`, carrying requested name, slug, and purpose. A taken slug returns 409 with suggestions; a free slug creates a pending Decision. Approving the Decision creates the project and makes the requester the lead member; denying it marks the request refused.
