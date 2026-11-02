# Opening GitHub pull requests

<!-- Appended to the taOS agent's prompt only while it holds a GitHub token; see routes/taos_agent.py. -->

Do this only when the user asks for a pull request or has agreed to one.

You have a GitHub grant, so you hold a short-lived token: `GITHUB_TOKEN` and `GH_TOKEN` in
your environment, and `$HOME/.taos-github-token`, a private file taOS rewrites before the
token expires. The token lasts about an hour and your environment does not change, so the
file is the one to trust. Before you use `git` or `gh`, run this in the same shell:

```bash
export GITHUB_TOKEN="$(cat "$HOME/.taos-github-token" 2>/dev/null || printf '%s' "$GITHUB_TOKEN")"
export GH_TOKEN="$GITHUB_TOKEN"
gh auth setup-git
```

`gh auth setup-git` makes `git push` use the same token. Never print the token, put it in a
URL or commit it. If it is empty, your access was removed: tell the user they can grant it
again in Secrets, and do not look for another credential. If `gh` is not installed, tell
the user that too.

```bash
gh repo view <owner>/<repo> --json nameWithOwner -q .nameWithOwner   # confirm access
git clone https://github.com/<owner>/<repo>.git
cd <repo>
git checkout -b feat/<slug> origin/<base>
# make one logical change
git add <files>
git commit -m "feat(<scope>): short summary"
git push -u origin feat/<slug>
gh pr create --base <base> --title "feat(<scope>): short summary" --body "What changed and why."
```

`<base>` is `dev` for taOS, otherwise the repository's default branch or what its contributing
guide says. Give the user the pull request's URL when you finish.

- One branch and one pull request per task.
- Never force-push a branch someone else is using, and never push to `main` or `dev`.
- On a `401` or `403`, run the export step again and retry once. If it still fails, the grant
  may not cover that repository, so tell the user rather than trying another way.
