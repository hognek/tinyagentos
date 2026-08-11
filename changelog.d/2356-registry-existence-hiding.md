### Security

- All owner-gated agent-registry routes are now existence-hiding: a caller who
  does not own an agent gets the same 404 as a nonexistent id, on the
  scope-request create/approve/deny routes and on registry PATCH, revoke,
  rotate-tokens, and org update. Previously a 403-vs-404 difference disclosed
  whether an agent id existed (issue #2106, reported by hognek) (#2356).
