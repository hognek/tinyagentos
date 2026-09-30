### Fixed

- The LLM gateway now serves rkllama and hailo-ollama chat models. Both
  expose `/v1/chat/completions` at the refs taOS installs, so the startup
  cutover no longer leaves their agents on LiteLLM. hailo-ollama streams
  Ollama NDJSON even on that path; the gateway turns it into OpenAI SSE
  chunks (role on the first delta, `finish_reason` from `done_reason`,
  `data: [DONE]` at the end) and records usage through the estimated path,
  since hailo reports no prompt token count. A hailo stream that errors or
  closes before `done: true` after tokens went out aborts (no finish chunk,
  no `[DONE]`), as the SSE path does, instead of ending as a clean `stop`.
- DeepSeek backends are forwarded as OpenAI-compatible (default base
  `https://api.deepseek.com/v1`, the backend's own key) instead of being
  refused as "cannot forward yet".
- Chat and embedding calls through the gateway reset the backend's
  lifecycle keep-alive timer, as LiteLLM's callback did via
  `/api/lifecycle/notify`. A notify failure never fails the request.
- taOS agent chat on the opencode harness no longer answers 503 "LiteLLM
  proxy is not running" when the gateway can serve its models. With no path
  at all, the 503 now says why the gateway could not carry it.
- `scripts/llm_gateway_parity.py` no longer reports an agent's trace count
  as unknown when one of its hourly trace buckets is a legacy file without a
  `trace_events` table; that bucket counts 0. Other sqlite errors (locked,
  corrupt) still make the count unknown.
- Agents whose keys were minted before the embedding alias was granted
  (every agent deployed before 2026-09-30) can embed again. Opening the key
  store grants `taos-embedding-default` to their live agent keys once, in
  both the legacy and gateway tables, so `/v1/embeddings` no longer answers
  403 `model_not_permitted` for them. It runs once per key store: a later
  deliberate removal of the alias sticks, and deny-all (empty) or revoked
  keys are left alone.
