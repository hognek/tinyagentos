### Changed

- The Hailo installer (`scripts/install-hailo.sh`) now checks for a pre-existing
  hailo-ollama instance on upstream port 8000 before any install or systemd
  mutation. When found (a server answering `GET /api/tags` with `"models"`), the
  script prints what was detected, reports that it would have built a second
  server on port 7836, and exits — leaving the existing instance untouched. This
  prevents the silent coexistence bug from issue #2083 where an upstream
  hailo-ollama (running on its default `0.0.0.0:8000`) would go unseen while
  taOS built a second server and installed no systemd unit.

### Fixed

- Detection of a pre-existing instance now exits with a distinct code (`3`)
  instead of `0`, so the auto-install callers (`install-server.sh`,
  `install-worker.sh`) no longer report silent success through their
  `|| warn` chain while leaving the box with no taOS backend on port 7836.
  Both callers key off exit 3 to tell the operator the install was skipped
  because a pre-existing hailo-ollama is already serving :8000, and the
  probe URL now uses `localhost` rather than `0.0.0.0`.
