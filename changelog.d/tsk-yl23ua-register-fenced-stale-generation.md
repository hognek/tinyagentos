### Fixed
- `POST /api/cluster/workers` now returns `409 Conflict` when the controller is fenced or the worker echoes a stale generation, instead of incorrectly replying `200 registered` while leaving the worker absent from the registry. This stops superseded controllers from misleading workers into heartbeating against a controller that has no record of them (#tsk-yl23ua).
