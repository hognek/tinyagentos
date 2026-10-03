### Fixed
- Moved the re-run helper for stale `bot-review-gate` runs into a separate `reconcile-stale-runs` job that checks out `github.event.pull_request.base.sha` instead of the PR merge ref, so the helper always executes from the base branch and cannot be replaced by a malicious PR. The `bot-review-gate` job no longer holds `actions: write`.
