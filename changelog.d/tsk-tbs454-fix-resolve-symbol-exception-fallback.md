### Fixed

- `scripts/check_deleted_symbols.py:_resolve_symbol` now falls back to an AST scan for ANY import-time failure (`Exception` and `SystemExit`), not just `SystemExit`. Missing optional dependencies and other import errors no longer cause false deletion reports. `KeyboardInterrupt` still propagates.

- `tests/test_check_deleted_symbols.py`: restored the accidentally deleted `TestResolveSymbolSymlinkTypechange` class. Added control tests for `sys.exit(2)` and `ImportError` at import time, with both symbol-present and symbol-absent cases.
