### Added

- Activity app: a **Model Activity** feed — a live timeline of model-level
  events (load, unload, eviction, shrink, route change, and inference request
  start/finish with duration and token rate) with filters for worker, model and
  event type. Backed by a bounded ring buffer on the controller, streamed to the
  app over SSE (`GET /api/activity/models/stream`, history at
  `GET /api/activity/models`). Request, token-rate and failover events come from
  the LLM gateway; the model load/unload/eviction/shrink hooks are on
  `CoreAwareModelScheduler` and start reporting once that scheduler is
  constructed with the feed. This is a separate surface from the AI-stack
  manager already in the Activity app's header.
