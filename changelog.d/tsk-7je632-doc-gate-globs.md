### Fixed
- Doc-gate and store-wiring now handle non-ASCII file paths correctly by using `git diff -z --name-status` with `core.quotePath=false`, so paths like `docs/café.md` trigger the intended rules instead of being silently skipped.
- `_glob_match` now correctly matches mid-pattern `**` (e.g. `docs/**/*.md` matches `docs/x.md` and `docs/a/b/x.md`) by emitting `(?:.*/)?` when `**` is followed by `/`.
- Store-wiring no longer flags a comment line like `# class Foo(BaseStore):` as a new class definition; it now parses the HEAD file with `ast` and returns True only when a real `ClassDef` named `class_name` exists in HEAD and not in base.
