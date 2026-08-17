### Fixed

- `check_all_skip.py` now reports zero-collected violations in the final `::error` annotation alongside all-skip violations, instead of incorrectly claiming "0 file(s) have all tests skipping" when only zero-collected files are present.
