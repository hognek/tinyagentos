### Fixed

- Unified the three mint paths that build a new agent key's allowed models into a single `scoped_key_models()` helper in `tinyagentos/llm_proxy.py`. All three call sites (`create_agent_key`, `deployer._mint_local_scoped_key`, `taos_agent_runtime._mint_local_taos_agent_key`) now use the same rule: `(models or ["default"]) + [EMBEDDING_ALIAS]` with no duplicate alias. This fixes the fallback-mint regression where a model-bearing deploy dropped the embedding alias, and restores the canonical model-first ordering.
