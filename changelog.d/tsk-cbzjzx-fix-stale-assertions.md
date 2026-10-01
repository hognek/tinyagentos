### Fixed
- Two stale assertions in `tests/test_litellm_master_key_callers.py` now expect every newly minted key to include the `taos-embedding-default` embedding alias in its allowed models list.
