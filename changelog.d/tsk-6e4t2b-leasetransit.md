### Fixed

- Fixed cluster lease over-admission during heartbeat transit (tsk-6e4t2b)
  - Added `vram_sampled_age_ms` to heartbeat payload so controller uses sample time instead of receipt time
  - Updated `claim_lease()` to count leases granted during heartbeat transit
  - Added `vram_sampled_at` field to `WorkerInfo` for internal tracking
  - Maintains backward compatibility with workers that don't send the new field
