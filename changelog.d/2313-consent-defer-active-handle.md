### Changed

- Approving an agent auth-request with `defer_binding` now returns 409 when that
  agent already has an active handle, and the response points the operator at
  `POST /api/projects/{project_id}/members/assign-agent`. It previously advised
  minting a second identity, which splits an agent's memory and grants across
  two canonical ids (#2313).
