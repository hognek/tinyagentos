### Fixed

- `claim_lease` no longer double-counts VRAM already reflected in `worker.free_vram_mb`. A lease is only subtracted from effective free when its `granted_at` post-dates the worker's last heartbeat, preserving the H1 race-window protection without silently losing capacity after allocation.
