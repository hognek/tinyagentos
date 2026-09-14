### Fixed

- Added `TAOS_SPA_DIR` environment variable support in `tinyagentos/routes/desktop.py` so that a non-editable `pip install .` can find the staged desktop bundle. The variable is checked first; if set, `SPA_DIR` resolves to that path. Otherwise the default `PROJECT_DIR / "static" / "desktop"` is used as before.