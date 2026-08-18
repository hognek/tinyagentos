### Added

- **Agent-as-a-Model turn execution**: `POST /v1/chat/completions` now drives a
  real one-shot agent turn (consented agent → opencode host-server seam →
  OpenAI ChatCompletion envelope) instead of returning 501. Per-agent opencode
  server cache so concurrent agents do not churn a shared singleton. Missing
  user message returns 400 (not 502); `stream` requires an explicit JSON
  boolean (#2195).