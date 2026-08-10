### Added

- The Agents app registry panel shows each agent's handle (alias) and lets the
  owner or an admin edit it inline, saved via
  `PATCH /api/agents/registry/{canonical_id}`. A leading `@` is display syntax
  and is stripped before save (#2349).
