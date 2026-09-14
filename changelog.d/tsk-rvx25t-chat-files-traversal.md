### Fixed
- `resolve_attachment` now rejects `../` traversal paths before opening or hashing any file outside `chat-files`, matching the existing containment in `serve_file`.
