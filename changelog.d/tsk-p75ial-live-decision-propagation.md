### Added

- Decision answers now propagate live across all open surfaces via SSE. When a decision is answered in one surface (chat or Decisions app), other surfaces update immediately without requiring a page refresh.

- Concurrency safety: first-answer-wins enforcement via atomic store-level `UPDATE ... WHERE status = 'pending'`. Concurrent answer attempts from multiple surfaces resolve to exactly one recorded answer; subsequent attempts receive a clean 409 response with no duplicate event broadcast.
