### Fixed

- Resolve `TAOS_SPA_DIR` at import and quote it in non-systemd launch commands so symlinked or relative SPA directories serve built assets instead of falling back to `index.html`.
