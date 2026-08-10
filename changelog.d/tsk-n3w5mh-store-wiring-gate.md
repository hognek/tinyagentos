### Added

- **CI**: store-wiring-gate workflow and `scripts/check_store_wiring.py` guard.
  A PR that adds a new BaseStore subclass without wiring it into
  `tinyagentos/app.py` now fails CI and names the unreachable class and file.
  Routes reach stores ONLY via `request.app.state`, so an unwired store is
  dead code. Start with a NAME-LEVEL check (class name appears in the lifespan
  file). Only newly added classes are policed; pre-existing orphans are not
  flagged. A `Store-Unwired-Intentionally: <ClassName>, <why>` trailer in the
  PR body waives a named class and logs it, for stores genuinely constructed
  elsewhere (tests, CLI, workers).
