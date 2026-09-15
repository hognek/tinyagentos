### Fixed

- `TAOS_SPA_DIR` is now set automatically by the installer (`scripts/install-server.sh`) on Linux systemd, user-unit, nohup fallback, and macOS launchd paths, pointing at `$INSTALL_DIR/static/desktop` so non-editable `pip install .` finds the staged desktop bundle. The three stray root bundle files (`chat.html`, `index.html`, `sw.js`) have been removed.
