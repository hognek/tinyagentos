### Fixed
- `test_guard_detects_stale_sniffio_namespace` no longer passes or fails depending on whether `sniffio` was imported during pytest collection. The stale-namespace helper now evicts the target module and any submodules from `sys.modules`, calls `importlib.invalidate_caches()`, and restores the originals in `finally` so later tests see a healthy environment.
