### Fixed
- BLE Reassembler.last_drop now resets on every feed() call, so it only names a drop caused by the current fragment (fixes stale drop reason bleeding into subsequent feeds).
- PairResponder now returns a named `weak_key` error frame for weak ephemeral/public keys (all-zero or low-order), instead of the generic `bad hello`. Malformed input still returns `bad hello`.
- `_validate_key_not_weak` now maps ANY ValueError from the trial X25519 exchange (including `Error computing shared key.` from cryptography 50.0.0 for low-order points) to `ValueError('weak_key')`, dropping the fragile substring match.
- PairResponder's hello handler now answers every ValueError from `_validate_key_not_weak` with a `weak_key` error frame, never an exception.