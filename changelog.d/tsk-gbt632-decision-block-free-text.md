### Fixed
- DecisionBlock free_text textarea now stores the raw value and trims only at submit, so trailing spaces and Shift+Enter newlines are no longer eaten on every keystroke
- DecisionBlock now surfaces the server's exact error reason (e.g. `already answered or not pending`) in the inline alert instead of the generic "Could not record answer."
