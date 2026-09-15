### Fixed
- Installer hardware self-check now reads the local auth token from `data/.auth_local_token` and passes it as Bearer auth on `/api/system/hardware/refresh`. On a fresh install where no admin account exists yet, the check fails loud with a clear "local auth token not found" message instead of silently skipping (cannot-see-reads-as-pass).
- `_detect_disk()` now correctly distinguishes microSD (sd) from eMMC (emmc) on `mmcblk` devices by checking for eMMC boot partitions (`mmcblkXboot0`, `mmcblkXrpmb`) and the sysfs device type attribute (`MMC` vs `SD`).
