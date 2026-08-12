### Added

- **LoRA Studio backend**: share a Civitai LoRA/LoCon/DoRA model URL and taOS
  archives it -- safetensors file (SHA256-verified), name, description,
  preview images, tags, and trigger words -- under a new `loras` store and
  `/api/loras/*` endpoints. Civitai's edge geo-blocks some regions with HTTP
  451; a new `lora_ingest_proxy_url` config key lets the fetcher (and only
  the fetcher) go out through an explicit proxy instead. Every failure mode
  (451, connect error, SHA256 mismatch, a non-LoRA model type) fails loud
  with a specific reason and leaves no partial file on disk. LoRA files live
  under `models_root()/loras/` and are excluded from the Models app's disk
  scan so adapters never show up as loadable models. `/api/library/ingest`
  also recognises Civitai URLs and delegates to the same ingest job.
