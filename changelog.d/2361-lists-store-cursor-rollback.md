### Fixed

- Project list entries: `get_entry` no longer reads cursor metadata after the
  cursor closes, and a failed reorder now rolls back its partial updates so a
  later unrelated write cannot commit a half-applied ordering (tsk-u23vjy,
  fix-forward of #2183).
