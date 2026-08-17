### Fixed
- DecisionsApp `load()` now guards each state update with a monotonically increasing request sequence, so a stale in-flight response can no longer overwrite newer data when mount, focus refresh, or SSE-driven reloads overlap
