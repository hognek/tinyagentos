### Fixed

- Restore error propagation from `answerDecision` so non-409 server failures (500, network errors, 4xx) surface the server-provided reason in the alert region instead of being swallowed
- Surface a fallback message when the post-409 refetch itself fails, rather than leaving the block pending with no feedback
