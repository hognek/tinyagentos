### Fixed

- `_commit_waivers` now unions all scoped trailers from a commit message instead of breaking on the first one. A commit with multiple `Docs-Reviewed: [scope]` lines now correctly waives all referenced rules.
- The CI log now lists every trailer override used in a commit instead of stopping after the first one.
