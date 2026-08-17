### Fixed
- A fenced (superseded) controller now releases GPU leases and cancels in-flight GPU arbiter tasks for its workers, matching the sibling termination branches. Previously it only marked workers offline and skipped the lease release and arbiter cancellation, stranding VRAM leases and allowing arbiter tasks to collide with the winning controller.
