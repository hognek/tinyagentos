### Added

- New pure dispatch policy module `tinyagentos/projects/dispatch_policy.py` with unserved-board-first fairness for fleet task assignment. Includes `is_candidate`, `is_board_dispatchable`, `Assignment` dataclass, and `select_assignments` function with anti-affinity fallback and per-board load tracking.