"""Model Activity feed endpoints.

``GET /api/activity/models``        paginated ring-buffer snapshot
``GET /api/activity/models/stream`` SSE stream of model-level events

Both are session-only: they expose which models the controller is loading and
who is calling them, so both require the ``get_current_user`` session dependency
(neither path is in ``auth_middleware.EXEMPT_PATHS``). A local/admin bearer
token, which the middleware would otherwise let through with a ``user_id``, is
NOT sufficient here.

Filters (``model`` / ``worker`` / ``event``) apply to the history snapshot and
to the live SSE frames alike; an unknown ``event`` is a 400 rather than a
silently empty feed.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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


def _validated_event(event: str | None) -> str | None:
    """Reject an unknown ``event`` filter instead of answering with nothing.

    A typo'd filter that silently returns an empty feed reads as "no activity
    happened", which is the wrong conclusion to hand a caller. Same posture as
    the a2a bus, which 400s unknown query parameters so an ignored filter can
    never look like a working one.
    """
    if event is not None and event not in EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown event type {event!r}; expected one of: "
                f"{', '.join(EVENT_TYPES)}"
            ),
        )
    return event


def _resume_seq(request: Request) -> int | None:
    """The last ``seq`` the client saw, from the SSE ``Last-Event-ID`` header.

    Browsers send this automatically on ``EventSource`` reconnect, so a client
    that drops for a moment is caught up from the ring instead of silently
    missing everything recorded during the gap. A malformed header is treated
    as "no resume" rather than an error: the worst case is the pre-existing
    behaviour (start from the current window).
    """
    raw = request.headers.get("last-event-id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


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
    event = _validated_event(event)
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
    _user: dict = Depends(get_current_user),
):
    """SSE stream of model-level events.

    A new subscriber is first sent the current ring-buffer window (oldest of
    that window first) and then every live event matching the filters.
    Keepalives go out every 10 s so proxies don't drop the connection.

    Reconnect: frames carry ``id: <seq>``, so a browser's ``EventSource`` sends
    ``Last-Event-ID`` on reconnect and the events recorded during the gap are
    replayed from the ring (still filtered). That is why the id is the event's
    monotonic ``seq`` rather than a per-connection counter.
    """
    event = _validated_event(event)

    feed = _feed(request)
    if feed is None:
        return JSONResponse({"detail": "Service starting"}, status_code=503)

    resume_seq = _resume_seq(request)
    # A resume id above anything this feed has issued is from a previous
    # process: the counter restarts at 1 after a controller restart, so
    # honouring it would set a watermark no new event can ever pass and mute
    # the feed for a client that was simply still reconnecting. Treat it as a
    # new connection instead.
    if resume_seq is not None and resume_seq > feed.last_seq:
        resume_seq = None

    # Subscribe BEFORE snapshotting so no event can slip between the two; the
    # snapshot's highest seq is the dedupe watermark for the live queue.
    queue = feed.subscribe()
    # On a resume the whole ring is eligible (the gap may exceed `limit`);
    # otherwise `limit` bounds the initial catch-up window.
    replay = list(reversed(feed.snapshot(
        limit=feed.maxlen if resume_seq is not None else limit,
        model=model,
        worker=worker,
        event=event,
    )))
    if resume_seq is not None:
        replay = [ev for ev in replay if ev.seq > resume_seq]
    # Mutable cell: gen() reassigns it, so a closure-local would read unbound.
    state = {"watermark": max(resume_seq or 0, replay[-1].seq if replay else 0)}

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