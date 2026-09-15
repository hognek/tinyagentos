### Fixed
- `_detect_disk()` now queries eMMC boot-partition sysfs paths with the block-device index preserved (`mmcblk0boot0`, `mmcblk0boot1`, `mmcblk0rpmb`) instead of stripping the index and checking non-existent `mmcblkboot0`/`mmcblkrpmb` paths.
