### Added
- Decisions now support append-only notes. `POST /api/decisions/{id}/note` records a text note on any decision (pending, answered, or superseded) without changing the decision state. Notes are returned by `GET /api/decisions/{id}` and list, and a `decision.note` SSE event keeps open surfaces live.
