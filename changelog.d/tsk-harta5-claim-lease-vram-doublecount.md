### Fixed

- `claim_lease` no longer double-counts VRAM already reflected in `worker.free_vram_mb`. A lease is only subtracted from effective free when its `granted_at` post-dates the worker's last heartbeat, preserving the H1 race-window protection without silently losing capacity after allocation.
- A vram-less heartbeat no longer ages live leases out of `already_held`; `claim_lease` now compares `granted_at` against `worker.last_vram_report_at` so only leases granted after the last actual VRAM sample are counted.
