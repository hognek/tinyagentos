### Fixed

- `check_all_skip.py` now treats files with 0 collected outcomes but >0 AST-defined tests as a violation, instead of silently passing the gate.
