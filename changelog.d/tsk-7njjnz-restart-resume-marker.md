### Fixed

- Restart resume now preserves user-set paused flags from the Agents app,
  disk quota, and failure handler by tracking a `paused_by_restart` marker
  that is set only when a restart prepare returns 200. Only agents carrying
  that marker are resumed or have their paused flag cleared on retry window
  expiry. A 200 prepare also deletes any stale controller note for that
  agent, so a later `/resume` POST is not blocked by an old note. Lifecycle
  calls are skipped for agents with no recorded port instead of guessing
  port 8080.
