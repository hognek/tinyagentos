### Fixed

- **Item 1 (LOST GUARD)**: Restored `test_updater_extras_match_install_server` test with proper guard against installer pip line, verifying the installer's final `pip install -e` line installs `.[\$(taos_controller_extras)]` and matches the lib's inlined function
- **Item 2 (PARITY REGEX)**: Fixed regex to extract full `taos_controller_extras()` function from install-server.sh, including the case block that was previously truncated
- **Item 3 (DEAD PATCH)**: Updated test patches to use `tinyagentos.routes.settings._detect_device_class` instead of `tinyagentos.hardware._detect_device_class`, fixing device probe routing
- **Item 4 (INERT TEST)**: Removed `test_installer_extras_repo_unchanged` test which was read-only and could never fail
- **Item 5 (KIOSK PIP USER)**: Fixed `scripts/kiosk-setup.sh` to run pip as the venv owner (`taos` service user) instead of the kiosk login user, preventing permission errors
- **Item 6 (TOP-LEVEL LOCAL)**: Removed `local venv_owner=""` at script top level in `scripts/kiosk-setup.sh` which caused the script to abort under `set -e` on the default BLE path
- **Item 7 (NIT)**: Updated comment in `tinyagentos/routes/settings.py` to reflect the correct installer pip line pattern
