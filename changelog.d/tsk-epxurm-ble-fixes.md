### Fixed

- Fixed BLE extras computation to run at update time instead of import time, eliminating systemctl subprocess calls during server startup
- Updated tests to not mutate module globals, using proper monkeypatch for _detect_device_class and environment variables
- Added test_install_extras_ble.py with comprehensive bash-level tests for taos_controller_extras function
- Enhanced fresh handset installation by adding ble extra installation in kiosk-setup.sh
- Fixed stray indentation in install-server.sh pip commands
