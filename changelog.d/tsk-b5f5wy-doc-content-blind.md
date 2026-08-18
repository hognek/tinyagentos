### Fixed
- The doc-gate content-blindness defect: a per-doc list of required section headings is now asserted present in the working tree. A `docs/agent-coordination.md` emptied of its protected API-surface sections now fails the `invariants` check instead of passing the gate indefinitely.
