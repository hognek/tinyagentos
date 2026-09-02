### Fixed
- Wake-budget enforcement test now closes the debounced task and creates a fresh ready task before the third tick, so the tick actually reaches `can_wake` and verifies that budget exhaustion blocks further wakes instead of silently skipping at debounce.
