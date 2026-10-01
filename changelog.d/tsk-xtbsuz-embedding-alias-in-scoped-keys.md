### Fixed

- Deployer and taOS agent runtime now include `taos-embedding-default` in every
  scoped per-agent key so deployed agents can embed through the gateway without
  a 403.

### Caveat

- On Postgres-mode installs (`inhouse_keys` off), LiteLLM has no `custom_auth`
  and rejects keystore-minted keys. Setting `TAOS_LLM_GATEWAY=0` (rollback to
  LiteLLM) breaks every agent deployed after this PR because its key is accepted
  only by the gateway. Stage 2b deletes the LiteLLM rollback path entirely.
