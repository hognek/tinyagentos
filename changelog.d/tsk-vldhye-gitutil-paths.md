### Fixed
- `scripts/_gitutil.py`: stop stripping git `-z` path fields in `parse_name_status` so paths with trailing whitespace are preserved verbatim, and guard `diff_name_status_z` with `base_ref=None` to raise `ValueError` instead of building `None...HEAD`.
