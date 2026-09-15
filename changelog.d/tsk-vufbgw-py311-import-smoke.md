### Added

- `py311-import-smoke` CI job runs on pull requests targeting dev or master (and on pushes to those branches), guarding the declared `requires-python = ">=3.11"` floor against import-time regressions that the nightly shard alone would not catch in time.