### Fixed
- `POST /api/store/install-v2` now validates `target_remote` at the API boundary before it is interpolated into backend daemon URLs (`resolve_rkllama_url`, LXC remote addressing). Hostile strings containing `:`, `/`, `?`, `#`, or `@` are rejected with HTTP 400 and a named `invalid_target_remote` reason, preventing SSRF-shaped installs or silent mis-routing to unregistered workers.
