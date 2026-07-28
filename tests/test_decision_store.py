import pytest
import pytest_asyncio

from tinyagentos.decisions.decision_store import DecisionStore


@pytest_asyncio.fixture
async def store(tmp_path):
    s = DecisionStore(tmp_path / "decisions.db")
    await s.init()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_create_and_get(store):
    d = await store.create(
        "@taOS-dev", "Build X first?", "single_select",
        options=[{"label": "A", "value": "a", "recommended": True, "rationale": "best"},
                 {"label": "B", "value": "b"}],
        context="why", project_id="prj-1", user_id="u1",
    )
    assert d["id"].startswith("dec-")
    assert d["status"] == "pending"
    assert d["options"][0]["recommended"] is True
    got = await store.get(d["id"])
    assert got["question"] == "Build X first?"


@pytest.mark.asyncio
async def test_invalid_type_rejected(store):
    with pytest.raises(ValueError):
        await store.create("@a", "q", "bogus_type")


@pytest.mark.asyncio
async def test_metadata_round_trips(store):
    meta = {"kind": "app_grant", "app_id": "stream-chat", "capabilities": ["app.net"]}
    d = await store.create("@a", "grant?", "multi_select",
                           options=[{"label": "Net", "value": "app.net"}], metadata=meta)
    assert d["metadata"] == meta
    got = await store.get(d["id"])
    assert got["metadata"] == meta
    # Omitted metadata defaults to an empty dict, not None.
    d2 = await store.create("@a", "q", "free_text")
    assert d2["metadata"] == {}


@pytest.mark.asyncio
async def test_list_filters(store):
    await store.create("@a", "q1", "approve_deny", project_id="p1", user_id="u1")
    b = await store.create("@a", "q2", "free_text", project_id="p2", user_id="u1")
    await store.answer(b["id"], "done", "u1")
    assert len(await store.list()) == 2
    assert len(await store.list(status="pending")) == 1
    assert len(await store.list(status="answered")) == 1
    assert len(await store.list(project_id="p1")) == 1
    assert len(await store.list(user_id="u1")) == 2


@pytest.mark.asyncio
async def test_answer_then_cannot_reanswer(store):
    d = await store.create("@a", "q", "approve_deny", user_id="u1")
    upd = await store.answer(d["id"], "approve", "u1")
    assert upd["status"] == "answered"
    assert upd["answer"]["value"] == "approve"
    assert upd["answer"]["answered_by"] == "u1"
    # second answer on a non-pending decision is rejected
    assert await store.answer(d["id"], "deny", "u1") is None


@pytest.mark.asyncio
async def test_answer_unknown_returns_none(store):
    assert await store.answer("dec-missing", "x", "u1") is None


@pytest.mark.asyncio
async def test_supersede(store):
    d = await store.create("@a", "q", "single_select",
                           options=[{"label": "x", "value": "x"}], user_id="u1")
    assert await store.supersede(d["id"]) is True
    assert (await store.get(d["id"]))["status"] == "superseded"


@pytest.mark.asyncio
async def test_branching_fields_reserved(store):
    d = await store.create("@a", "q", "free_text", user_id="u1",
                           parent_decision_id="dec-parent", checkpoint_ref="abc123",
                           timeline_id="t1")
    got = await store.get(d["id"])
    assert got["parent_decision_id"] == "dec-parent"
    assert got["checkpoint_ref"] == "abc123"
    assert got["timeline_id"] == "t1"


@pytest.mark.asyncio
async def test_list_filter_from_agent(store):
    """from_agent filter returns only decisions raised by that agent."""
    await store.create("@agent-x", "q1", "free_text", user_id="u1")
    await store.create("@agent-y", "q2", "free_text", user_id="u1")
    x_only = await store.list(from_agent="@agent-x")
    assert len(x_only) == 1
    assert x_only[0]["from_agent"] == "@agent-x"


@pytest.mark.asyncio
async def test_list_filter_metadata_kind(store):
    """metadata_kind filter matches JSON metadata with a substring."""
    await store.create("@a", "q1", "free_text", user_id="u1",
                       metadata={"kind": "execution_gate"})
    await store.create("@a", "q2", "free_text", user_id="u1",
                       metadata={"kind": "app_grant"})
    await store.create("@a", "q3", "free_text", user_id="u1", metadata={})
    exec_only = await store.list(metadata_kind="execution_gate")
    assert len(exec_only) == 1
    assert exec_only[0]["metadata"]["kind"] == "execution_gate"


@pytest.mark.asyncio
async def test_list_filter_pending_age_gt(store, monkeypatch):
    """pending_age_gt returns only pending decisions older than the threshold."""
    import time as _time
    d = await store.create("@a", "q", "free_text", user_id="u1")
    # Simulate passage of time by moving the clock forward, so the created_at
    # timestamp is in the "distant past" relative to now.
    fake_now = d["created_at"] + 120  # 2 minutes later
    monkeypatch.setattr(_time, "time", lambda: fake_now)
    # Threshold of 60s: this decision was created 120s ago, so it matches.
    old = await store.list(status="pending", pending_age_gt=60)
    assert len(old) == 1
    # Threshold of 200s: too recent, should not match.
    none_found = await store.list(status="pending", pending_age_gt=200)
    assert len(none_found) == 0


@pytest.mark.asyncio
async def test_answer_source_persistence(store):
    """Answer source field is persisted and round-trips correctly."""
    d = await store.create("@a", "q", "approve_deny", user_id="u1")
    upd = await store.answer(d["id"], "approve", "u1", source="in_app")
    assert upd["answer"]["source"] == "in_app"

    d2 = await store.create("@a", "q2", "approve_deny", user_id="u1")
    upd2 = await store.answer(d2["id"], "deny", "u1", source="mirrored_from_chat")
    assert upd2["answer"]["source"] == "mirrored_from_chat"

    # Default source
    d3 = await store.create("@a", "q3", "approve_deny", user_id="u1")
    upd3 = await store.answer(d3["id"], "approve", "u1")
    assert upd3["answer"]["source"] == "in_app"
