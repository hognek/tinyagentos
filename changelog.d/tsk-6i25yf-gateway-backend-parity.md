### Fixed

- The LLM gateway now serves rkllama and hailo-ollama chat models. Both
  expose `/v1/chat/completions` at the refs taOS installs, so the startup
  cutover no longer leaves their agents on LiteLLM. hailo-ollama streams
  Ollama NDJSON even on that path; the gateway turns it into OpenAI SSE
  chunks (role on the first delta, `finish_reason` from `done_reason`,
  `data: [DONE]` at the end) and records usage through the estimated path,
  since hailo reports no prompt token count.
- DeepSeek backends are forwarded as OpenAI-compatible (default base
  `https://api.deepseek.com/v1`, the backend's own key) instead of being
  refused as "cannot forward yet".
- Chat and embedding calls through the gateway reset the backend's
  lifecycle keep-alive timer, as LiteLLM's callback did via
  `/api/lifecycle/notify`. A notify failure never fails the request.
- taOS agent chat on the opencode harness no longer answers 503 "LiteLLM
  proxy is not running" when the gateway can serve its models. With no path
  at all, the 503 now says why the gateway could not carry it.
