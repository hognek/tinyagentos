### Fixed

- Wrap the four `/sys/block/{name}boot0`, `{name}boot1`, `{name}rpmb`, and `/sys/block/{name}/device/type` probes in `_detect_disk()` with `_path_exists_safe()` so `PermissionError` on Python 3.11 does not crash `detect_hardware()` and instead falls back to `sd`.
