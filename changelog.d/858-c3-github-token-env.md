### Added

- taOS agent sessions now inherit the agent's granted short-lived GitHub token as `GITHUB_TOKEN`/`GH_TOKEN`, rotated before expiry during long sessions; agent containers ship `git` + `gh`, and a PR-ops skill teaches the branch → PR flow (#858).