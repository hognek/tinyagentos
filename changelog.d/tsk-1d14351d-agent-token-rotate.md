### Added

- `POST /api/agents/registry/{canonical_id}/rotate-tokens` now replaces the
  credential ON the same canonical identity and returns the new token in the
  response, instead of only bumping `token_min_iat`. The cutoff moves to
  `now + 1` and the replacement is minted at that cutoff, so a token minted in
  the same second is superseded rather than surviving its own rotation. Owner
  or admin may rotate an identity they own; an agent may rotate its OWN
  identity with its own live registry JWT (the route joins the middleware's
  Bearer allowlist), giving agents the self-service "rotate my credential"
  action they lacked. Mint responses (register, mint-internal, auth-request
  poll, rotate) now carry a `storage_guidance` field: store the token in two
  migration-surviving locations, mode 0600, outside git. (taOS #2158)

### Fixed

- `rotate_native_agent_token` used `now` as the rotation cutoff, so rotating in
  the second right after a mint left the previous token unsuperseded. It now
  uses `now + 1` and mints the replacement at the resulting cutoff.
