### Added

- Speech backends: `whisper`, `kokoro`, and `moss` backend types are now registered in the backend catalog. A `whisper` server (faster-whisper / whisper.cpp) advertises the `asr` capability; `kokoro` (Kokoro TTS server) and `moss` (MOSS TTS via SGLang/vLLM-Omni) advertise `tts`. Workers running these servers are probed by default (whisper :9000, kokoro :8880, moss :30000) and can be selected via `TaskRouter.route_request("asr")` / `("tts")`. The worker-models manifest maps `whisper`, `kokoro`, and `moss` software entries to their backend types (#3231).
