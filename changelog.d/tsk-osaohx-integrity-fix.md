### Fixed
- Removed the install.method: hailo-ollama-pull carve-out from the model manifest integrity test; every variant (including HEF/hailo-ollama) must now carry a 64-char lowercase hex sha256 and a non-empty https download_url. The _is_stride2_algorithmic detector that supported the deleted carve-out has been removed.
