### Added
- GPU arbiter now presents its lease epoch on renew and release, so a lease taken over by another holder stops the running task instead of being silently renewed.