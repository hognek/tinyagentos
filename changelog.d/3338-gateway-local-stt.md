### Added

- **Local speech-to-text in the LLM gateway**: `POST /api/llm/v1/audio/transcriptions` (OpenAI-compatible multipart, `json` or `text` response) transcribes 16 kHz mono PCM WAV up to 30 s through the on-device `taos-sttd` daemon on `127.0.0.1`. The upload is capped while it streams and is never written to disk; there is no cloud fallback. Helpers live in `tinyagentos/llm_gateway/stt.py` for reuse by a device voice route.
