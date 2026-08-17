### Fixed
- Removed `tinyagentos/containers.py`, which had been unreachable dead code since the `containers/` package landed. Edits to the shadowed module silently no-opped at runtime; the package copy at `tinyagentos/containers/__init__.py` is what all imports resolve to.
