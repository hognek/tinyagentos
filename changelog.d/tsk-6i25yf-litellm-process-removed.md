### Removed

- The LiteLLM proxy process is gone. The controller no longer spawns,
  health-checks, restarts or self-heals LiteLLM, writes no LiteLLM config,
  master key or callback shims, and binds nothing on `server.litellm_port`.
  Every agent's chat, stream and embedding already went through the
  in-process LLM gateway; it is now the only LLM path.
- The `proxy` extra (litellm and its 29 inlined proxy dependencies) is out of
  `pyproject.toml` and `uv.lock`. The installer and the Settings updater
  install no extra by default (a handset still adds `ble`), and the installer
  no longer sets up a local Postgres for LiteLLM virtual keys. The LiteLLM
  service manifest is gone from the app catalog.
- `scripts/llm_gateway_parity.py` lost its side-by-side LiteLLM mode; the
  gateway check (formerly `--gateway-only`) is the only mode, and the flag
  is still accepted as a no-op.

### Changed

- `TAOS_LLM_GATEWAY=0` (or `false` / `no` / `off`) no longer turns the gateway
  off or moves agents back to LiteLLM: there is no LiteLLM to roll back to.
  The value is ignored and logged once at startup.
- At startup every agent container whose `taos-proxy-litellm` device still
  connects to an old LiteLLM host port (4000, 7834, or the configured
  `server.litellm_port`) is moved to the gateway's agent listener
  unconditionally. An agent whose key cannot be mirrored or whose models the
  gateway cannot route is still moved, with the reason logged, instead of
  being left on a dead port. A device is never moved onto a listener this
  start could not verify as its own. The device keeps its
  `taos-proxy-litellm` name and its in-container `127.0.0.1:4000` listen
  side; there is no rename migration.
- Remote agent deploys are refused with "remote agents need the network LLM
  gateway, not built yet" (the gateway's agent listener is loopback-only).
  They were handed LiteLLM over the network before.
- New local deploys get `OPENAI_BASE_URL=http://127.0.0.1:4000/v1` and
  `TAOS_EMBEDDING_URL=http://127.0.0.1:4000/v1/embeddings`, the container's
  own proxy-device address, whatever the host's `litellm_port` is. Fresh
  installs used to inject `http://localhost:7834/v1`, which no container can
  reach. A local deploy is refused, with the reason, when this controller
  start has not verified its gateway listener.
- The macOS launchd agent the installer writes now runs `python -m tinyagentos`
  instead of bare uvicorn, so the gateway's agent listener starts there too
  (it is every agent's only LLM path now). A controller started with bare
  `uvicorn tinyagentos.app:create_app --factory` has no agent listener and
  refuses local agent deploys with the reason.
- `/api/settings/llm-proxy` always reports the gateway (`mode: gateway`) and
  no longer carries a `litellm` block.
- The taOS agent's opencode harness always uses the in-process gateway; when
  the gateway cannot serve the model the chat answers 503 with the reason.

### Fixed

- Agent key mint, re-scope and delete no longer silently do nothing when
  LiteLLM is not running: re-minting an agent's key (openclaw), restoring an
  archived agent (which now also scopes the new key to the agent's models and
  pushes `LITELLM_API_KEY` beside `OPENAI_API_KEY`) and deleting the
  archived agent's key-store key all work against the local key store
  directly.
