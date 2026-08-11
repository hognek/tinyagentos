### Fixed

- The Agent-as-a-Model surface (`GET /v1/models`, `POST /v1/chat/completions`)
  is now reachable by external OpenAI-compatible clients: the auth middleware
  passes exactly those two routes through to their own consent-key check
  instead of rejecting every session-less caller before the handler ran. All
  other `/v1` paths remain session-gated (tsk-hfs6zv).
