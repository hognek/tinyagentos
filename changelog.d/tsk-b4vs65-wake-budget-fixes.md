### Fixed

- Config validation now rejects non-integer values (floats, bools) for global_default, per_agent, and per_project budgets. Previously `0.9` was accepted and truncated to `0`, silently disabling scheduled wakes fleet-wide.
- Damaged wake_budget.json state now reports unknown/damaged state (consumed:0, remaining:0) instead of full budget (consumed:0, remaining:budget) when can_wake returns False.
- Fleet wake-info now preserves the first successful read when the second read fails, maintaining consistency across the two read surfaces.
- Null wake_budget (None) is now tolerated as defaults, matching the documented/returned default of 2.
