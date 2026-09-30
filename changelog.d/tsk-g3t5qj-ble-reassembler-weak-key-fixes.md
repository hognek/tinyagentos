### Fixed
- BLE Reassembler.last_drop now resets on every feed() call, so it only names a drop caused by the current fragment (fixes stale drop reason bleeding into subsequent feeds).
- PairResponder now returns a named `weak_key` error frame for weak ephemeral/public keys (all-zero or low-order), instead of the generic `bad hello`. Malformed input still returns `bad hello`.
- PairResponder and PairInitiator now also refuse keys whose trial X25519 exchange returns an all-zero shared secret (defensive for older cryptography builds), mapping any ValueError from the trial exchange to `weak_key`.