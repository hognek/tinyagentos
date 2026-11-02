# Skill: GitHub PR workflow (git + gh)

<!-- Agent-facing skill for opening pull requests with granted GitHub access.
Framework-agnostic: applies to any adapter/agent runtime, not just opencode. -->

This skill teaches you the branch -> PR flow for opening a pull request with
your granted GitHub access. It works the same way under any agent framework and
any adapter.

## Token

Your taOS session is given a short-lived GitHub token scoped to the
installations your agent is granted. It is exposed to you as:

- `GITHUB_TOKEN` (and `GH_TOKEN`) in your environment at session start.
- A 0600 credential file at `$HOME/.taos-github-token`.

The token expires after about **1 hour** and is rotated in the background by
your controller. Because the environment of a long-running process is fixed at
spawn, before any `git push` or `gh pr create` re-export the freshest value as
a belt-and-suspenders step:

```bash
export GITHUB_TOKEN="$(cat "$HOME/.taos-github-token" 2>/dev/null || echo "$GITHUB_TOKEN")"
```

If the file and env var are both unset, you have not been granted GitHub
access — do not guess a token; tell the human.

## Verify access first

Before pushing, confirm you can reach the repo:

```bash
gh auth status
gh repo view <owner>/<repo> --json nameWithOwner -q .nameWithOwner
```

## Branch -> PR flow

1. **Clone** (or work inside your project checkout):

   ```bash
   git clone https://github.com/<owner>/<repo>.git
   cd <repo>
   ```

2. **Branch** off the integration branch (default target is `dev`):

   ```bash
   git checkout dev
   git pull --ff-only
   git checkout -b feat/<slug>        # or fix/<slug>
   ```

3. **Make changes** — one logical change per branch.

4. **Commit** with a conventional-commit style message:

   ```bash
   git add .
   git commit -m "feat(<scope>): short summary"
   ```

5. **Push** the branch:

   ```bash
   git push -u origin feat/<slug>
   ```

6. **Open the pull request** against the base branch:

   ```bash
   gh pr create --base dev --title "feat(<scope>): short summary" \
     --body "What changed and why. Link the taOS task id if applicable."
   ```

   If a PR for the branch already exists, `gh pr create` prints its URL — you
   can instead `gh pr view` it and push amend commits to update it.

## Rules

- Always target the integration branch (`dev`), never `main`, unless told
  otherwise.
- Rebase on the base branch with `git pull --ff-only` before pushing if the
  remote moved; prefer a clean linear history.
- Never force-push a shared branch. `git push --force-with-lease` only on your
  own feature branch before review.
- One branch / one PR per task, matching `feat/<slug>` or `fix/<slug>`.
- If the push or PR create fails with `401`/`403`, the token may be expired —
  re-export from `$HOME/.taos-github-token` and retry. Still failing, tell the
  human.
