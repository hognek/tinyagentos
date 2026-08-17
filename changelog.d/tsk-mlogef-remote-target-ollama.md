### Fixed
- Ollama and hailo-ollama installs targeted at a remote worker (`target_remote`) now pull models onto that worker's daemon instead of the controller's localhost; `resolve_ollama_url(target_remote, backend_id)` selects the correct host and port (11434 for ollama, 7836 for hailo-ollama via `TAOS_HAILO_OLLAMA_PORT`) following the same convention as `resolve_rkllama_url`.
