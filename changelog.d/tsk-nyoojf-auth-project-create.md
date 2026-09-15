### Fixed

- project_create auth requests now require a resolved agent identity (valid registry token or registered handle); unauthenticated or unresolved identities receive 401 instead of being assigned to a caller-chosen handle.
- The pending cap is enforced before the Decision row is created, and the cap is keyed by the resolved canonical id in a fixed project-create namespace so varying the caller-chosen framework cannot bypass it.
- Project, member and lead writes are wrapped in a single transaction on approval; a failure after project creation deletes the project and marks the request refused, and granted_scopes are only recorded when the grant write succeeds.
