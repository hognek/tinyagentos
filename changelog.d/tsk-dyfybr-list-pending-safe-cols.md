### Fixed
- `list_pending` in `device_pair_requests_store.py` now selects only `_SAFE_COLS` instead of `SELECT *`, preventing leakage of columns outside the allowed set such as `verify_code`.
