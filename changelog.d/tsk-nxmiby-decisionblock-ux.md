### Fixed

- Disable option buttons and Submit button while a POST is in flight, preventing duplicate submissions that cause 409 errors
- Clear answerError at the start of each new submission attempt
- Distinguish refresh-failure from submit-failure: when POST succeeds but follow-up GET fails, do not show "Failed to answer"
- On 409 (someone else answered first), refetch the decision so the block flips to its answered state
- Reset answer and answerError state when block.decision_id changes