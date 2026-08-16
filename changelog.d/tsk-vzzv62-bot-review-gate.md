### Added
- A `scripts/check_bot_review.py` gate that fails (exit 1) when the only CodeRabbit output on a PR is a rate-limit stub, so the merge path no longer treats a passing "Review rate limited" check as a real review. Runs on every PR targeting `master` or `dev` via `.github/workflows/bot-review-gate.yml` (tsk-vzzv62).
