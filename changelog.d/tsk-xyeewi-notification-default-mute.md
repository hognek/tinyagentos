### Fixed

- **Dropped the hardcoded mute on `task.claimed` notifications.** The per-type
  toggle preferences remain, but no event type is silenced by default. A user
  who has never opened the Notifications pane now receives every event type,
  including `task.claimed`. A regression test asserts delivery of an
  unmodified-user `task.claimed` notification, so re-introducing a silent
  default mute will fail CI.
