### Added

- Agents with a GitHub grant now receive their short-lived token as `GITHUB_TOKEN`/`GH_TOKEN` and in `~/.taos-github-token`, rotated before it expires. This covers the taOS agent under opencode and local agent containers. Agent images and new deploys include `gh`, and the taOS agent gets the pull request flow in its prompt while it holds a token (taOS #858).

### Fixed

- `get_agent_github_token` read a config field removed when the GitHub App key moved to Secrets, so it raised on any install with a GitHub App configured. It now reads the key from Secrets (taOS #858).
