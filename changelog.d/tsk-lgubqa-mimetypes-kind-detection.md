### Fixed
- `.yaml`, `.yml`, `.toml`, and `.log` files now route to `TextProcessor` for text extraction instead of falling through to `FileProcessor`. `detect_kind` now uses `mimetypes.guess_type` with a `text/*` rule for MIME-based detection and a small `_EXT_OVERRIDE_MAP` for the few extensions mimetypes gets wrong.
