# Agent GitHub access

How an agent with a GitHub grant gets a token and opens a pull request (taOS #858). The
user side (connecting an account, granting it to an agent) is in the Secrets app.

## How a token reaches an agent

`tinyagentos/github_token.py` mints a GitHub App installation token, which lasts an hour, for
any agent with a `github-installation` grant. Delivery has two parts, because a process's
environment cannot change after it starts:

- `GITHUB_TOKEN` and `GH_TOKEN` in the environment, set at start.
- A 0600 credential file, `.taos-github-token` in the agent's home, which stays current.

`github_token_refresh_loop` rewrites the file every 4 minutes, inside the 5 minutes before a
cached token expires. A failed mint leaves the current file alone. A removed grant deletes it,
but the token already issued stays valid at GitHub until it expires, at most an hour later.

| Agent | Environment | File and rotation |
|---|---|---|
| taOS agent under opencode | At server start | `<data_dir>/taos-agent-opencode-*/` |
| Local agent container | At deploy | `/root/.taos-github-token` |
| Agents using the host opencode through `routes/agent_model_api.py` | None | None |
| taOS agent under PicoClaw or Claude Code | None | None |
| Remote agent containers | None | None |

The agents on `agent_model_api.py` share the taOS agent's runtime code. They must never receive
its token, so only the taOS agent's chat route passes `github_agent` to
`ensure_taos_opencode_server`.

## Instructions and tools

The compiled manual is at its size limit, so the pull request flow is a conditional chapter,
`docs/agent-manual/github/github-prs.md`, added to the taOS agent's prompt only while it holds a
token. Agents in containers are not given these instructions yet.

`gh` comes from the agent base images and the cold-install package list. The host installers
try to install it for the taOS agent, and carry on without it if they cannot.

## Known limits

- A token covers one installation. An agent granted several gets a token for the first that
  mints, so pushes to repositories in the others fail.
- This builds on the GitHub App flow. The OAuth identities and time-scoped sharing Jay described
  on #858 are not implemented here.
