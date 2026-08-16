### Fixed
- Fixed DecisionBlock free_text textarea no longer posts on every keystroke; onChange now updates local state only, Enter submits once, and a visible Submit button is provided
- Surface answerDecision errors inline instead of unhandled promise rejections
- Removed unreachable duplicate conditions in dayLabel