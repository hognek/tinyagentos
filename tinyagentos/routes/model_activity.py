"""Model Activity feed endpoints.

``GET /api/activity/models``        paginated ring-buffer snapshot
``GET /api/activity/models/stream`` SSE stream of model-level events

Both are session-only: they expose which models the controller is loading and
who is calling them, so an unauthenticated request is rejected (the SSE path is
NOT in ``auth_middleware.EXEMPT_PATHS``; the handler re-checks ``user_id`` so a
middleware bypass produces a clear 401 rather than an open stream).

Filters (``model`` / ``worker`` / ``event``) apply to the history snapshot and
to the live SSE frames alike.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from tinyagentos.auth import get_current_user
from tinyagentos.model_activity import EVENT_TYPES, ModelActivityEvent

router = APIRouter()

#: How many recent events a fresh SSE subscriber is caught up with before the
#: live stream takes over.  Bounded so a reconnect cannot replay a huge window.
_REPLAY_LIMIT = 50

_KEEPALIVE_SECONDS = 10.0


def _feed(request: Request):
    return getattr(request.app.state, "model_activity", None)


def _matches(
    ev: ModelActivityEvent,
    *,
    model: str | None,
    worker: str | None,
    event: str | None,
) -> bool:
    if model is not None and ev.model != model:
        return False
    if worker is not None and ev.worker != worker:
        return False
    if event is not None and ev.event != event:
        return False
    return True


def _frame(ev: ModelActivityEvent) -> str:
    return f"id: {ev.seq}\ndata: {json.dumps(ev.to_dict())}\n\n"


@router.get("/api/activity/models")
async def model_activity_history(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    model: str | None = None,
    worker: str | None = None,
    event: str | None = Query(None, description=f"one of: {', '.join(EVENT_TYPES)}"),
    _user: dict = Depends(get_current_user),
):
    """Recent model-level events, newest first."""
    feed = _feed(request)
    if feed is None:
        return {"events": [], "count": 0, "event_types": list(EVENT_TYPES)}
    events = feed.snapshot(limit=limit, model=model, worker=worker, event=event)
    return {
        "events": [ev.to_dict() for ev in events],
        "count": len(events),
        "event_types": list(EVENT_TYPES),
    }


@router.get("/api/activity/models/stream")
async def model_activity_stream(
    request: Request,
    limit: int = Query(_REPLAY_LIMIT, ge=0, le=500),
    model: str | None = None,
    worker: str | None = None,
    event: str | None = None,
):
    """SSE stream of model-level events.

    A new subscriber is first sent the current ring-buffer window (oldest of
    that window first) and then every live event matching the filters.
    Keepalives go out every 10 s so proxies don't drop the connection.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    feed = _feed(request)
    if feed is None:
        return JSONResponse({"detail": "Service starting"}, status_code=503)

    # Subscribe BEFORE snapshotting so no event can slip between the two; the
    # snapshot's highest seq is the dedupe watermark for the live queue.
    queue = feed.subscribe()
    replay = list(reversed(feed.snapshot(limit=limit, model=model, worker=worker, event=event)))
    # Mutable cell: gen() reassigns it, so a closure-local would read unbound.
    state = {"watermark": replay[-1].seq if replay else 0}

    async def gen():
        try:
            for ev in replay:
                yield _frame(ev)
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
                    continue
                if ev.seq <= state["watermark"]:
                    continue
                state["watermark"] = ev.seq
                if not _matches(ev, model=model, worker=worker, event=event):
                    continue
                yield _frame(ev)
        finally:
            feed.unsubscribe(queue)

    # Cache-Control/X-Accel-Buffering keep nginx and friends from buffering the
    # stream (which would coalesce or delay frames).
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )