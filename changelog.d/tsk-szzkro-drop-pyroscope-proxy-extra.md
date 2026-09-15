### Fixed

- Removed `pyroscope-io` from the `proxy` extra: the pinned range
  (`>=0.8.16,<1.0`) resolved to a single release that ships no musllinux
  wheel and no sdist, so `pip install -e ".[proxy]"` failed outright on any
  musl host (Alpine, postmarketOS). Nothing in the codebase imports it.
