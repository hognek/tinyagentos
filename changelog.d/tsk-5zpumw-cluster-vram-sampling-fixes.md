### Fixed

- Route `POST /api/cluster/heartbeat` now forwards `vram_sampled_age_ms` into `ClusterManager.heartbeat()` so the controller derives the VRAM sample time instead of using the receipt time.
- Restored `already_held` VRAM accounting block inside its guard with correct indentation so `effective_free` is evaluated once per claim, not per lease.
- Worker sends `None` for `vram_sampled_age_ms` when no VRAM probe is available instead of `0`, allowing the controller to distinguish "unknown" from "no VRAM free".
- Removed duplicate `worker.vram_sampled_at = None` assignment, orphan comment, and unused `vram_sampled_at` field from heartbeat body.
- Consolidated changelog fragments to reference `tsk-6e4t2b` only.
