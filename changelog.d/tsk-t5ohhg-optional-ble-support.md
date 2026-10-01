### Added
- Added `ble` extra (bleak) support for taOSmobile handsets. The installer and settings updater now detect handsets via `hardware._detect_device_class()` and install the `ble` extra on handsets to enable Orb BLE scan/pair routes. Operators can override this behavior using the `TAOS_EXTRAS_BLE=1` or `TAOS_EXTRAS_BLE=0` environment variables.
- Added `taos_controller_extras()` bash function in `scripts/install-server.sh` for device-class-based extras selection.
- Added test coverage in `tests/test_updater_extras_ble.py` for handset detection and extras selection logic.
