### Added

- **Doc-drift gate covers the full doc surface**: the invariants scan now
  takes globs and checks every agent-manual page, runbook, OS skill
  (`.claude/skills/*/SKILL.md`), the worker README, CONTRIBUTING and
  RELEASING for references to files that no longer exist (with a documented
  tombstone list for deliberate mentions of removed files). Three new
  diff-gate rules: desktop-driving route changes require the taos-agent
  skill / OS-control manual reviewed, update/release machinery changes
  require RELEASING.md or a runbook reviewed, and worker-tree changes
  require the worker README. RELEASING.md now documents the sync-branch
  promotion pattern for a BEHIND dev->master PR, including the back-merge
  and empty-tree-diff identity check.
