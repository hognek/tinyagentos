### Added

- **Settings-update brings a locally-hosted taOSmd to latest in the same
  action**: with the new config keys `taosmd_dir` and `taosmd_restart_cmd` set
  (and `memory_url` local), `POST /api/settings/update` ff-only-pulls the
  taOSmd checkout, announces the restart on the A2A bus `build` thread before
  dropping SSE subscribers, restarts the service, and then verifies the
  RUNNING server's `/health` — Content-Type must be `application/json` (a
  `text/html` 200 from the SPA catch-all fails) and the core capability
  identifiers (`a2a.v1`, `collections.v1`, `search.v1`) must be present in the
  body. Any taOSmd failure fails the whole update loudly with a named reason;
  unconfigured or remote installs get an explicit `taosmd: {"skipped": <why>}`
  in the response, never a silent half-update (tsk-jjkukj).
