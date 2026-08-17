### Fixed
- `scripts/collate_changelog.py` is now idempotent across partial failures: if a run dies between writing the new version section and unlinking consumed fragments, a rerun detects the existing `## [<version>]` header and skips the duplicate insert while still consuming any leftover fragments.
