### Added

- Quarantined task cards surface their strike count and latest strike on the
  task-detail response, and a lead can un-quarantine a card via
  `POST /api/projects/{pid}/tasks/{tid}/unquarantine`, clearing its strikes (#2333).
