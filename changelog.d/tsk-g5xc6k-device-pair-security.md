### Fixed
- Device pair-request creation: enforce the pending cap atomically so concurrent requests cannot bypass it.
- Device pair-request creation: return 409 Conflict when no instance admin exists, instead of silently creating an unapprovable request.
