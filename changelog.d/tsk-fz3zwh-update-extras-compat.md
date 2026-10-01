### Added

- CI gate that fails when an extra present in the merge-base `pyproject.toml` or `uv.lock` is deleted at the PR head, forcing authors to empty extras (`name = []`) instead of removing them.
- Self-maintaining updater-extras test that drives `_compute_update_extras()` through every branch (mobile/non-mobile x `TAOS_EXTRAS_BLE` unset/1/0/true/false) and asserts every returned extra is in `SHIPPED_UPDATER_EXTRAS` and defined in both `pyproject.toml` and `uv.lock`.
