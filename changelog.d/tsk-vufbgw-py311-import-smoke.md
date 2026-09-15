### Added

- `py311-import-smoke` CI job runs on every PR and push, guarding the declared `requires-python = ">=3.11"` floor against import-time regressions that the nightly shard alone would not catch in time.