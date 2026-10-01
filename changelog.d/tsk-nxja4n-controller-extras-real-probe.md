### Fixed

- real handset probe in `controller_extras.sh` via `systemctl cat taos-kiosk.service`
- `install-server.sh` inlines `taos_controller_extras` so `curl | sh` works
- `kiosk-setup.sh` honours `TAOS_INSTALL_DIR` and `TAOS_EXTRAS_BLE=0`, installs as service user
- updater parity test now compares Python and shell helper output for identical inputs
- `llm_proxy` self-heal uses `_compute_update_extras()` so handset gets `--extra ble`
