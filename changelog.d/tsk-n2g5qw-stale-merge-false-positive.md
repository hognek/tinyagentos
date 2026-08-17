### Fixed
- deleted-symbols CI gate no longer reports false positives on `pull_request` re-runs after the base advances: the merge result is recomputed in-script via `git merge-tree --write-tree <base> <pr-head>` (`scripts/check_deleted_symbols.py`) instead of comparing the event-time test-merge commit checked out as HEAD
