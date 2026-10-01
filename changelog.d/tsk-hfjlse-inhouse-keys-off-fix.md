### Fixed
- Remote agent deployments are now refused when `inhouse_keys` is off (Postgres-backed install), because local key-store keys are not accepted by LiteLLM in that mode. The error message names the `.litellm_force_inhouse_keys` marker remedy.
- The taOS agent runtime now correctly handles legacy (non-local-store) keys: when re-scoping fails, it mints a fresh local-store key instead of keeping the legacy one.
- The taOS agent runtime now errors with the `.litellm_force_inhouse_keys` marker remedy when a local key would be routed to LiteLLM directly while `inhouse_keys` is off (gateway disabled or models_problem).
- Updated stale comments in `deployer.py` to describe the local key store as the only mint path.
- Fixed documentation in `agent-coordination.md` to reflect that `scoped_key_models` adds the embedding alias to every mint and re-scope.