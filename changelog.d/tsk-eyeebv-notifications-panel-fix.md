### Fixed

- NotificationsPanel now correctly shows error messages when the prefs fetch fails instead of displaying a permanent loading state. Added a `loaded` flag to track when the initial fetch has settled, distinguishing between genuine loading and error states.