### Security

- Memory routes reject any `agent` value that is not a single plain path
  component (separators, `.`/`..`, NUL all 400): the caller-controlled name
  becomes a filesystem path component of the qmd `dbPath`, and a traversal
  value could previously address SQLite files outside `agent-memory/` (#2352).
