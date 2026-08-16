### Fixed
- Fixed hardware_tiers YAML indentation in five HEF manifests (deepseek-r1-1.5b, qwen2-1.5b, qwen2.5-1.5b, qwen2.5-coder-1.5b, qwen3-1.7b) so tier keys nest under hardware_tiers instead of parsing as null.
- Removed two a8w4 variants with fabricated sha256 pins (llama-3.2-1b/a8w4 and qwen3-1.7b/a8w4) that returned HTTP 404 on their download_url.
- Extended the model manifest integrity test with a denylist of known-fabricated digests and a hardware_tiers nesting check (no stray tier keys at variant level; hardware_tiers must be a non-empty mapping).
