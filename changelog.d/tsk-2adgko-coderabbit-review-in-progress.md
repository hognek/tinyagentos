### Fixed

- bot-review-gate now treats CodeRabbit's "review in progress" placeholder as a stub rather than a completed review. A comment carrying the `review in progress by coderabbit.ai` marker means the review is still running, so the gate must stay red until CodeRabbit posts the completed walkthrough. This prevents a fake-green merge when CodeRabbit edits its in-progress placeholder into the auto-summary comment before the review finishes (as happened on PR #3322).
