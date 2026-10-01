### Fixed
- Fixed model-less deploy key losing the default chat alias. The embedding alias is now properly granted for agents deployed without an explicit model, allowing them to chat without a 403 error. This was done by:
  1. Adding the embedding alias inside `llm_proxy.create_agent_key` (same way `update_agent_key` already does)
  2. Reverting `deployer.py` to pass `models=key_models or None` (dropping its own alias-adding branch)
  3. Dropping the alias append in `taos_agent_runtime.py`
  4. Ensuring the local key store also includes the embedding alias
