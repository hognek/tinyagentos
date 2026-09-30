### Fixed

- Fixed usage header in `scripts/install-hailo.sh` to document the correct default directory `~<user>/hailo_model_zoo_genai` instead of the incorrect `~<user>/hailo-ollama`
- Updated corresponding documentation in `docs/design/hailo-llm-backend.md` to match the actual install directory default
- Verified all other default values in the header (REF, PORT, REPO) against the actual code defaults and confirmed they were already correct