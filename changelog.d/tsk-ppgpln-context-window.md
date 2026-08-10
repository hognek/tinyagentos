### Fixed

- **Catalog manifests' `context_window` was silently dropped**: `AppManifest`
  declared no `context_window` field and `from_dict` never read the YAML
  value, so every manifest loaded as 0 and the chat context-window budget code
  always fell back to the 4000-token "unknown window" default. The field now
  loads onto `AppManifest` (0 reserved for unknown), so real windows — e.g.
  rkllm 4096, qwen 32768 — drive the #1740 budget math. (#2338, #1740)
