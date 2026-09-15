### Fixed

- Drop the `_SpDir` Path subclass from `tinyagentos/routes/desktop.py` and resolve `SPA_DIR` once at import with a plain `Path(os.environ.get("TAOS_SPA_DIR") or (_PROJECT_DIR / "static" / "desktop"))`. This fixes the `AttributeError: type object '_SpDir' has no attribute '_flavour'` that prevented the controller from starting on Python 3.11 (the declared `requires-python` floor). `TAOS_SPA_DIR` is now documented in README.md and named in both 404 error bodies.
