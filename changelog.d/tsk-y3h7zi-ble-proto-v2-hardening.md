### Fixed

- BLE proto v2 hardening: validate weak hello keys before commit, refuse unknown fragment flags, and report all drop reasons distinctly
- Board side (PairResponder): now validates static and ephemeral public keys in hello parsing for weak/low-order keys
- Controller side (PairInitiator): now validates board public keys in hello commit for weak/low-order keys
- Reassembler: validates unknown fragment flags and reports drop reasons via last_drop attribute
- Added last_drop tracking for inflight, oversize, orphan, duplicate-first, and bad-flags drops
- pairing.py: logs drop reasons when fragments are dropped