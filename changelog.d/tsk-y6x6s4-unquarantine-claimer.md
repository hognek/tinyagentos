### Fixed

- **Un-quarantined cards return to a genuinely claimable pool**:
  `unquarantine_task` set the card back to `open` but kept the old
  `claimed_by`, and `claim_task` requires an unclaimed row -- so a
  claimed-then-quarantined card came back permanently unclaimable.
  Un-quarantine now clears the claimer, matching `reopen_task` and
  `release_task`.
