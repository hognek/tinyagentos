"""Tests for the Model Activity feed (#208).

The card's red-first pair:
  (a) the ring buffer records an event emitted by a scheduler / proxy hook
  (b) the SSE endpoint streams that event to a subscriber

plus the ring semantics (boundedness, filters, fan-out) and the HTTP surface.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from tinyagentos.llm_gateway.forward import _clear_cooldowns, chat_completion
from tinyagentos.llm_gateway.resolve import Route
from tinyagentos.model_activity import (
    MODEL_EVICT,
    MODEL_LOAD,
    MODEL_ROUTE,
    MODEL_SHRINK,
    MODEL_UNLOAD,
    REQUEST_FINISH,
    REQUEST_START,
    ModelActivityFeed,
)
from tinyagentos.routes.model_activity import model_activity_stream
from tinyagentos.scheduler.core_aware_scheduler import CoreAwareModelScheduler
from tinyagentos.scheduler.loaded_model import LoadedModel, PriorityClass
from tinyagentos.scheduler.resource_shape import BackendResourceShape

pytestmark = pytest.mark.asyncio

_RK3588 = BackendResourceShape(backend_type="rkllama", cores=[0, 1, 2], memory_mb=8192)
_NPU_URL = "http://npu.test/v1/chat/completions"


@pytest.fixture(autouse=True)
def _clean_cooldowns():
    """Failover cooldowns are module-global; never leak them between tests."""
    _clear_cooldowns()
    yield
    _clear_cooldowns()


@pytest.fixture
def feed(app):
    """Attach a fresh feed to the app.

    The shared ``client`` fixture bypasses the lifespan (which is what creates
    ``app.state.model_activity``), so tests that exercise the HTTP surface must
    install one -- the same pattern conftest uses for other lifespan-owned
    stores.
    """
    f = ModelActivityFeed()
    app.state.model_activity = f
    return f


def _shape_lookup(_backend: str) -> BackendResourceShape:
    return _RK3588


def _resident(
    model_id: str,
    cores: list[int],
    priority: str = PriorityClass.INTERACTIVE,
    backend: str = "rkllama",
) -> LoadedModel:
    tp = "all" if sorted(cores) == [0, 1, 2] else ",".join(str(c) for c in cores)
    return LoadedModel(
        model_id=model_id,
        backend=backend,
        memory_mb_used=512,
        resource_holds={"cores": list(cores)},
        tp_mode=tp,
        priority=priority,
    )


def _route(backend_name: str, api_base: str, model: str = "qwen3-8b") -> Route:
    return Route(
        model_name=model,
        provider="openai",
        upstream_model=model,
        api_base=api_base,
        api_key_ref=None,
        backend_name=backend_name,
    )


def _chat_body(model: str = "qwen3-8b") -> dict:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}]}


def _completion(prompt: int = 7, completion: int = 3) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def _fake_state(feed: ModelActivityFeed) -> SimpleNamespace:
    """The only attributes forward.py touches, and only optionally."""
    return SimpleNamespace(
        model_activity=feed, trace_registry=None, data_dir=None, secrets=None,
    )


# ---------------------------------------------------------------------------
# Ring buffer semantics
# ---------------------------------------------------------------------------

async def test_ring_buffer_is_bounded_and_seq_is_monotonic():
    feed = ModelActivityFeed(maxlen=3)
    for i in range(5):
        feed.record(MODEL_LOAD, model=f"m{i}")
    events = feed.snapshot(limit=10)
    assert [e.model for e in events] == ["m4", "m3", "m2"]  # newest first
    assert [e.seq for e in events] == [5, 4, 3]
    assert len(feed) == 3
    assert feed.stats()["capacity"] == 3
    assert feed.last_seq == 5


async def test_last_seq_is_zero_before_anything_is_recorded():
    feed = ModelActivityFeed()
    assert feed.last_seq == 0
    feed.record(MODEL_LOAD, model="a")
    assert feed.last_seq == 1


async def test_snapshot_filters_by_model_worker_and_event():
    feed = ModelActivityFeed()
    feed.record(MODEL_LOAD, model="a", worker="controller")
    feed.record(MODEL_LOAD, model="b", worker="pi-4")
    feed.record(MODEL_EVICT, model="a", worker="pi-4")

    assert [e.model for e in feed.snapshot(model="a")] == ["a", "a"]
    assert [e.worker for e in feed.snapshot(worker="pi-4")] == ["pi-4", "pi-4"]
    assert [e.event for e in feed.snapshot(event=MODEL_EVICT)] == [MODEL_EVICT]
    assert feed.snapshot(limit=0) == []


async def test_record_fans_out_to_every_subscriber():
    feed = ModelActivityFeed()
    q1 = feed.subscribe()
    q2 = feed.subscribe()
    ev = feed.record(MODEL_LOAD, model="a")
    assert q1.get_nowait() is ev
    assert q2.get_nowait() is ev
    feed.unsubscribe(q1)
    feed.record(MODEL_LOAD, model="b")
    assert q2.get_nowait().model == "b"
    assert feed.stats()["subscribers"] == 1


async def test_slow_subscriber_drops_oldest_not_newest():
    """A stalled reader must never grow memory without bound, and must be able
    to catch up on the most recent activity."""
    feed = ModelActivityFeed(subscriber_maxlen=1)
    q = feed.subscribe()
    feed.record(MODEL_LOAD, model="first")
    feed.record(MODEL_LOAD, model="second")
    assert q.get_nowait().model == "second"


async def test_maxlen_must_be_positive():
    with pytest.raises(ValueError):
        ModelActivityFeed(maxlen=0)


# ---------------------------------------------------------------------------
# (a) scheduler hook -> ring buffer
# ---------------------------------------------------------------------------

async def test_scheduler_load_and_unload_hooks_record_activity():
    feed = ModelActivityFeed()
    sched = CoreAwareModelScheduler(shape_lookup=_shape_lookup, activity_feed=feed)

    sched.register_loaded(_resident("qwen3-8b", [0, 1, 2]))
    sched.mark_unloaded("qwen3-8b")

    events = feed.snapshot()
    assert [e.event for e in events] == [MODEL_UNLOAD, MODEL_LOAD]
    load, unload = events[1], events[0]
    assert load.model == "qwen3-8b"
    assert load.backend == "rkllama"
    assert load.worker == "controller"
    assert unload.model == "qwen3-8b"
    # The registry entry is gone by emit time, so the backend rides the event.
    assert unload.backend == "rkllama"


async def test_scheduler_eviction_hook_records_model_evict():
    feed = ModelActivityFeed()
    sched = CoreAwareModelScheduler(shape_lookup=_shape_lookup)
    # Seed a single-core background resident holding the core we want.  A
    # one-core victim cannot be shrunk, so the pressure path must evict it.
    sched.register_loaded(_resident("old-embed", [2], PriorityClass.BACKGROUND))

    observed = ModelActivityFeed()
    sched.set_activity_feed(observed)
    model = await sched.load_with_core_awareness(
        "new-chat", "rkllama", requested_cores=[2], priority=PriorityClass.INTERACTIVE,
    )

    assert model.tp_mode == "2"
    events = observed.snapshot()
    assert [e.event for e in events] == [MODEL_EVICT]
    assert events[0].model == "old-embed"
    assert events[0].backend == "rkllama"
    assert events[0].reason == PriorityClass.BACKGROUND


async def test_scheduler_shrink_hook_records_model_shrink():
    feed = ModelActivityFeed()
    sched = CoreAwareModelScheduler(shape_lookup=_shape_lookup)
    sched.register_loaded(_resident("solo", [0, 1, 2], PriorityClass.BACKGROUND))

    observed = ModelActivityFeed()
    sched.set_activity_feed(observed)
    model = await sched.load_with_core_awareness(
        "incoming", "rkllama", requested_cores=[0], priority=PriorityClass.INTERACTIVE,
    )

    assert model.tp_mode == "0"
    events = observed.snapshot()
    assert [e.event for e in events] == [MODEL_SHRINK]
    assert events[0].model == "solo"
    assert events[0].detail["new_tp_mode"] == "1,2"


async def test_scheduler_without_a_feed_still_works():
    """The hook is optional: an unwired scheduler behaves exactly as before."""
    sched = CoreAwareModelScheduler(shape_lookup=_shape_lookup)
    sched.register_loaded(_resident("m", [0]))
    assert [e[0] for e in sched.events] == ["model_loaded"]
    assert sched.mark_unloaded("m") is not None


# ---------------------------------------------------------------------------
# (a) proxy hook -> ring buffer
# ---------------------------------------------------------------------------

@respx.mock
async def test_gateway_records_request_start_and_finish_with_token_rate():
    feed = ModelActivityFeed()
    state = _fake_state(feed)
    respx.post(_NPU_URL).mock(return_value=httpx.Response(200, json=_completion()))

    await chat_completion([_route("test-backend", "http://npu.test/v1")], _chat_body(), "agent-a", state)

    events = feed.snapshot()
    assert [e.event for e in events] == [REQUEST_FINISH, REQUEST_START]
    finish, start = events

    assert start.model == "qwen3-8b"
    assert start.backend == "test-backend"
    assert start.detail["principal"] == "agent-a"

    assert finish.model == "qwen3-8b"
    assert finish.backend == "test-backend"
    assert finish.tokens_in == 7
    assert finish.tokens_out == 3
    assert finish.duration_ms is not None and finish.duration_ms >= 0
    assert finish.token_rate is not None and finish.token_rate > 0
    assert finish.reason is None


@respx.mock
async def test_gateway_records_request_finish_on_upstream_5xx():
    feed = ModelActivityFeed()
    state = _fake_state(feed)
    respx.post(_NPU_URL).mock(return_value=httpx.Response(503, json={"error": "boom"}))

    with pytest.raises(Exception):
        await chat_completion([_route("test-backend", "http://npu.test/v1")], _chat_body(), "agent-a", state)

    finishes = [e for e in feed.snapshot() if e.event == REQUEST_FINISH]
    assert len(finishes) == 1
    assert finishes[0].reason == "http_503"


@respx.mock
async def test_gateway_records_request_finish_on_non_json_200():
    """A 200 whose body is not a JSON object still closes the start event."""
    feed = ModelActivityFeed()
    state = _fake_state(feed)
    respx.post(_NPU_URL).mock(return_value=httpx.Response(200, content=b"not json"))

    with pytest.raises(Exception):
        await chat_completion([_route("test-backend", "http://npu.test/v1")], _chat_body(), "agent-a", state)

    finishes = [e for e in feed.snapshot() if e.event == REQUEST_FINISH]
    assert len(finishes) == 1
    assert finishes[0].reason == "bad_response"


@respx.mock
async def test_failover_records_a_route_change():
    feed = ModelActivityFeed()
    state = _fake_state(feed)
    respx.post("http://down.test/v1/chat/completions").mock(
        return_value=httpx.Response(503, json={"error": "boom"})
    )
    respx.post("http://up.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )

    await chat_completion(
        [
            _route("down-backend", "http://down.test/v1"),
            _route("up-backend", "http://up.test/v1"),
        ],
        _chat_body(),
        "agent-a",
        state,
    )

    routes = [e for e in feed.snapshot() if e.event == MODEL_ROUTE]
    assert len(routes) == 1
    assert routes[0].model == "qwen3-8b"
    assert routes[0].backend == "up-backend"
    assert routes[0].reason == "failover"
    assert routes[0].detail["previous_backend"] == "down-backend"


@respx.mock
async def test_stream_completion_records_finish_with_tokens():
    feed = ModelActivityFeed()
    state = _fake_state(feed)
    sse = (
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post(_NPU_URL).mock(return_value=httpx.Response(200, content=sse))

    from tinyagentos.llm_gateway.forward import _event_stream_for_route

    gen = _event_stream_for_route(_route("test-backend", "http://npu.test/v1"), _chat_body(), "agent-a", state)
    chunks = [chunk async for chunk in gen]

    assert any(b"hi" in c for c in chunks)
    finishes = [e for e in feed.snapshot() if e.event == REQUEST_FINISH]
    assert len(finishes) == 1
    assert finishes[0].reason is None
    assert finishes[0].tokens_in == 5
    assert finishes[0].tokens_out == 2


@respx.mock
async def test_stream_abort_still_records_a_finish():
    """A client disconnect must not leave an orphan request.start."""
    feed = ModelActivityFeed()
    state = _fake_state(feed)
    sse = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    respx.post(_NPU_URL).mock(return_value=httpx.Response(200, content=sse))

    from tinyagentos.llm_gateway.forward import _event_stream_for_route

    gen = _event_stream_for_route(_route("test-backend", "http://npu.test/v1"), _chat_body(), "agent-a", state)
    first = await gen.__anext__()
    assert b"hi" in first
    await gen.aclose()

    events = feed.snapshot()
    assert [e.event for e in events] == [REQUEST_FINISH, REQUEST_START]
    assert events[0].reason == "aborted"


async def test_feed_is_optional_for_the_gateway():
    """No app.state.model_activity (e.g. flag off): a request still succeeds."""
    state = SimpleNamespace(trace_registry=None, data_dir=None, secrets=None)
    with respx.mock(assert_all_called=False) as mock:
        mock.post(_NPU_URL).mock(return_value=httpx.Response(200, json=_completion()))
        body = await chat_completion([_route("test-backend", "http://npu.test/v1")], _chat_body(), "a", state)
    assert body["choices"][0]["message"]["content"] == "hi"


# ---------------------------------------------------------------------------
# (b) SSE endpoint -> subscriber
# ---------------------------------------------------------------------------

def _sse_request(
    feed: ModelActivityFeed | None,
    *,
    headers: dict | None = None,
) -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    req.app.state.model_activity = feed

    async def _not_disconnected() -> bool:
        return False

    req.is_disconnected = _not_disconnected
    return req


#: The stream requires the session dependency; direct handler calls pass it in.
_USER = {"id": "user-1"}


def _parse_frame(chunk: bytes | str) -> dict:
    text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
    assert text.startswith("id: ")
    data_line = next(line for line in text.splitlines() if line.startswith("data: "))
    return json.loads(data_line[len("data: "):])


async def test_stream_replays_recorded_events_oldest_first():
    feed = ModelActivityFeed()
    feed.record(MODEL_LOAD, model="first")
    feed.record(MODEL_UNLOAD, model="second")

    resp = await model_activity_stream(_sse_request(feed), limit=50, model=None, worker=None, event=None, _user=_USER)
    it = resp.body_iterator
    try:
        first = _parse_frame(await asyncio.wait_for(it.__anext__(), timeout=5))
        second = _parse_frame(await asyncio.wait_for(it.__anext__(), timeout=5))
    finally:
        await it.aclose()

    assert first["event"] == MODEL_LOAD and first["model"] == "first"
    assert second["event"] == MODEL_UNLOAD and second["model"] == "second"


async def test_stream_pushes_a_live_event_to_its_subscriber():
    """The card's (b): a recorded event reaches a connected subscriber."""
    feed = ModelActivityFeed()
    resp = await model_activity_stream(_sse_request(feed), limit=50, model=None, worker=None, event=None, _user=_USER)
    it = resp.body_iterator

    async def _emit() -> None:
        await asyncio.sleep(0)
        feed.record(MODEL_LOAD, model="qwen3-8b", backend="rkllama")
        await asyncio.sleep(0)

    emitter = asyncio.ensure_future(_emit())
    try:
        chunk = await asyncio.wait_for(it.__anext__(), timeout=5)
    finally:
        emitter.cancel()
        await it.aclose()

    ev = _parse_frame(chunk)
    assert ev["event"] == MODEL_LOAD
    assert ev["model"] == "qwen3-8b"
    assert ev["worker"] == "controller"
    assert feed.stats()["subscribers"] == 0  # unsubscribed on close


async def test_stream_applies_filters_to_live_events():
    feed = ModelActivityFeed()
    resp = await model_activity_stream(
        _sse_request(feed), limit=50, model=None, worker="pi-4", event=None, _user=_USER,
    )
    it = resp.body_iterator

    async def _emit() -> None:
        await asyncio.sleep(0)
        feed.record(MODEL_LOAD, model="ignored", worker="controller")
        feed.record(MODEL_LOAD, model="wanted", worker="pi-4")
        await asyncio.sleep(0)

    emitter = asyncio.ensure_future(_emit())
    try:
        chunk = await asyncio.wait_for(it.__anext__(), timeout=5)
    finally:
        emitter.cancel()
        await it.aclose()

    ev = _parse_frame(chunk)
    assert ev["model"] == "wanted"
    assert ev["worker"] == "pi-4"


async def test_stream_requires_a_session(app, feed):
    """Session-only: no cookie means 401 from the dependency, not an open
    stream. A local/admin bearer token is not accepted here either."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as no_auth:
        resp = await no_auth.get("/api/activity/models/stream")
    assert resp.status_code == 401


async def test_stream_without_a_feed_reports_service_starting():
    req = _sse_request(None)
    req.app.state.model_activity = None
    resp = await model_activity_stream(req, limit=50, _user=_USER)
    assert resp.status_code == 503


async def test_stream_resumes_from_last_event_id():
    """A reconnect replays only the events newer than the client's last seq."""
    feed = ModelActivityFeed()
    for i in range(1, 4):
        feed.record(MODEL_LOAD, model=f"m{i}")

    resp = await model_activity_stream(
        _sse_request(feed, headers={"last-event-id": "2"}),
        limit=50, model=None, worker=None, event=None, _user=_USER,
    )
    it = resp.body_iterator
    try:
        resumed = _parse_frame(await asyncio.wait_for(it.__anext__(), timeout=5))
    finally:
        await it.aclose()

    assert resumed["seq"] == 3
    assert resumed["model"] == "m3"


async def test_stream_resume_ignores_the_catch_up_limit():
    """The gap can exceed `limit`; a resume must still see the whole ring."""
    feed = ModelActivityFeed()
    for i in range(1, 4):
        feed.record(MODEL_LOAD, model=f"m{i}")

    resp = await model_activity_stream(
        _sse_request(feed, headers={"last-event-id": "1"}),
        limit=0, model=None, worker=None, event=None, _user=_USER,
    )
    it = resp.body_iterator
    try:
        seqs = []
        for _ in range(2):
            seqs.append(_parse_frame(await asyncio.wait_for(it.__anext__(), timeout=5))["seq"])
    finally:
        await it.aclose()

    assert seqs == [2, 3]


async def test_stream_treats_a_resume_id_ahead_of_the_feed_as_a_new_connection():
    """A controller restart resets seq to 1. A client reconnecting with an id
    from the previous process must not have every new event suppressed."""
    feed = ModelActivityFeed()
    feed.record(MODEL_LOAD, model="m1")

    resp = await model_activity_stream(
        _sse_request(feed, headers={"last-event-id": "9999"}),
        limit=50, model=None, worker=None, event=None, _user=_USER,
    )
    it = resp.body_iterator

    async def _emit() -> None:
        await asyncio.sleep(0)
        feed.record(MODEL_LOAD, model="m2")
        await asyncio.sleep(0)

    emitter = asyncio.ensure_future(_emit())
    try:
        first = _parse_frame(await asyncio.wait_for(it.__anext__(), timeout=5))
        second = _parse_frame(await asyncio.wait_for(it.__anext__(), timeout=5))
    finally:
        emitter.cancel()
        await it.aclose()

    assert first["model"] == "m1"   # the window is replayed as a new connection
    assert second["model"] == "m2"  # and the new live event is NOT suppressed


async def test_stream_treats_a_malformed_last_event_id_as_no_resume():
    feed = ModelActivityFeed()
    feed.record(MODEL_LOAD, model="only")

    resp = await model_activity_stream(
        _sse_request(feed, headers={"last-event-id": "not-a-number"}),
        limit=50, model=None, worker=None, event=None, _user=_USER,
    )
    it = resp.body_iterator
    try:
        first = _parse_frame(await asyncio.wait_for(it.__anext__(), timeout=5))
    finally:
        await it.aclose()

    assert first["model"] == "only"


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

async def test_history_endpoint_returns_events_newest_first(client, feed):
    feed.record(MODEL_LOAD, model="a")
    feed.record(MODEL_UNLOAD, model="b")

    resp = await client.get("/api/activity/models")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [e["event"] for e in body["events"]] == [MODEL_UNLOAD, MODEL_LOAD]
    assert body["count"] == 2
    # The vocabulary is advertised so the UI can build its filter list.
    assert MODEL_ROUTE in body["event_types"]


async def test_history_endpoint_filters_and_limit(client, feed):
    feed.record(MODEL_LOAD, model="a", worker="controller")
    feed.record(MODEL_LOAD, model="b", worker="pi-4")
    feed.record(MODEL_EVICT, model="a", worker="pi-4")

    by_model = await client.get("/api/activity/models", params={"model": "a"})
    assert {e["model"] for e in by_model.json()["events"]} == {"a"}

    by_worker = await client.get("/api/activity/models", params={"worker": "pi-4"})
    assert {e["worker"] for e in by_worker.json()["events"]} == {"pi-4"}

    by_event = await client.get("/api/activity/models", params={"event": MODEL_EVICT})
    assert [e["event"] for e in by_event.json()["events"]] == [MODEL_EVICT]

    limited = await client.get("/api/activity/models", params={"limit": 1})
    assert limited.json()["count"] == 1


async def test_history_endpoint_requires_auth(app, feed):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as no_auth:
        resp = await no_auth.get("/api/activity/models")
    assert resp.status_code == 401


async def test_sse_stream_route_is_registered(app):
    """httpx's ASGITransport buffers a response to completion, so an endless SSE
    body cannot be driven through it; the handler itself is covered above and
    this pins that the endpoint is actually mounted."""
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/activity/models/stream" in paths
    assert "/api/activity/models" in paths


async def test_history_endpoint_rejects_an_unknown_event_filter(client, feed):
    """A typo'd filter must not read as "nothing happened"."""
    resp = await client.get("/api/activity/models", params={"event": "model.explode"})
    assert resp.status_code == 400
    assert "model.explode" in resp.json()["detail"]


async def test_stream_rejects_an_unknown_event_filter():
    from fastapi import HTTPException

    feed = ModelActivityFeed()
    with pytest.raises(HTTPException) as excinfo:
        await model_activity_stream(_sse_request(feed), limit=50, event="nope", _user=_USER)
    assert excinfo.value.status_code == 400


async def test_to_dict_hands_out_a_copy_of_detail():
    """The record is frozen; a caller mutating the serialised dict must not
    reach back into the stored event."""
    feed = ModelActivityFeed()
    feed.record(MODEL_LOAD, model="a", detail={"tp_mode": "all"})

    payload = feed.snapshot()[0].to_dict()
    payload["detail"]["tp_mode"] = "mutated"

    assert feed.snapshot()[0].detail == {"tp_mode": "all"}


async def test_app_lifespan_attaches_the_feed(app):
    from tinyagentos.model_activity import ModelActivityFeed as _Feed

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.model_activity, _Feed)