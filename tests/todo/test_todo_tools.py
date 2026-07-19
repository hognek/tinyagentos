"""Tests for the todo agent tools (todo_list_lists, todo_add_item, todo_set_done)."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from tinyagentos.todo.todo_store import TodoStore
from tinyagentos.tools.todo_tools import (
    execute_todo_add_item,
    execute_todo_list_lists,
    execute_todo_set_done,
)


# --------------------------------------------------------------------- helpers

def _make_request(store, config=None, msg_store=None):
    state = types.SimpleNamespace(
        todo_store=store,
        config=config,
        chat_messages=msg_store,
    )
    app = types.SimpleNamespace(state=state)
    return types.SimpleNamespace(app=app)


@pytest_asyncio.fixture
async def store(tmp_path):
    s = TodoStore(tmp_path / "test_todo_tools.db")
    await s.init()
    yield s
    await s.close()


# ------------------------------------------------------------------ list tests

@pytest.mark.asyncio
async def test_list_returns_owned_lists(store):
    doc = await store.create_list("user-1", "Shopping")
    await store.create_list("user-2", "Other List")

    req = _make_request(store)
    res = await execute_todo_list_lists(
        {"agent_name": "atlas", "owner_user_id": "user-1"}, req
    )
    assert "lists" in res
    assert any(d["id"] == doc["id"] for d in res["lists"])
    assert len(res["lists"]) == 1


@pytest.mark.asyncio
async def test_list_excludes_other_users_lists(store):
    await store.create_list("user-2", "Private")

    req = _make_request(store)
    res = await execute_todo_list_lists(
        {"agent_name": "atlas", "owner_user_id": "user-1"}, req
    )
    assert res["lists"] == []


@pytest.mark.asyncio
async def test_list_excludes_archived_lists(store):
    doc = await store.create_list("user-1", "Old List")
    await store.archive_list(doc["id"])

    req = _make_request(store)
    res = await execute_todo_list_lists(
        {"agent_name": "atlas", "owner_user_id": "user-1"}, req
    )
    assert res["lists"] == []


@pytest.mark.asyncio
async def test_list_missing_agent_name_returns_error(store):
    req = _make_request(store)
    res = await execute_todo_list_lists({}, req)
    assert "error" in res


@pytest.mark.asyncio
async def test_list_missing_owner_user_id_returns_error(store):
    req = _make_request(store)
    res = await execute_todo_list_lists({"agent_name": "atlas"}, req)
    assert "error" in res


# ------------------------------------------------------------------- add tests

@pytest.mark.asyncio
async def test_owner_can_add_item(store):
    doc = await store.create_list("user-1", "Shopping")

    req = _make_request(store)
    res = await execute_todo_add_item(
        {"agent_name": "atlas", "list_id": doc["id"], "text": "Buy milk",
         "owner_user_id": "user-1"},
        req,
    )
    assert res.get("ok") is True
    assert "item_id" in res

    items = await store.list_items(doc["id"])
    assert any(i["text"] == "Buy milk" for i in items)


@pytest.mark.asyncio
async def test_non_owner_rejected(store):
    doc = await store.create_list("user-1", "Private")

    req = _make_request(store)
    res = await execute_todo_add_item(
        {"agent_name": "atlas", "list_id": doc["id"], "text": "Hacked",
         "owner_user_id": "user-2"},
        req,
    )
    assert "error" in res
    assert "access" in res["error"]

    items = await store.list_items(doc["id"])
    assert items == []


@pytest.mark.asyncio
async def test_add_item_attributed_to_agent(store):
    doc = await store.create_list("user-1", "Tasks")

    req = _make_request(store)
    res = await execute_todo_add_item(
        {"agent_name": "atlas", "list_id": doc["id"], "text": "Do the thing",
         "owner_user_id": "user-1"},
        req,
    )
    item = await store.get_item(res["item_id"])
    assert item["author"] == "atlas"


@pytest.mark.asyncio
async def test_add_item_notification_noop(store):
    """Notification module is a no-op for now; just verify the add succeeds."""
    doc = await store.create_list("user-1", "Ideas")

    req = _make_request(store)
    res = await execute_todo_add_item(
        {"agent_name": "atlas", "list_id": doc["id"], "text": "Interesting",
         "owner_user_id": "user-1"},
        req,
    )
    assert res.get("ok") is True


@pytest.mark.asyncio
async def test_add_item_missing_fields_returns_error(store):
    req = _make_request(store)

    res = await execute_todo_add_item(
        {"agent_name": "atlas", "list_id": "list-x", "owner_user_id": "user-1"}, req
    )
    assert "error" in res

    res = await execute_todo_add_item(
        {"agent_name": "atlas", "text": "hi", "owner_user_id": "user-1"}, req
    )
    assert "error" in res

    res = await execute_todo_add_item(
        {"list_id": "list-x", "text": "hi", "owner_user_id": "user-1"}, req
    )
    assert "error" in res

    res = await execute_todo_add_item(
        {"agent_name": "atlas", "list_id": "list-x", "text": "hi"}, req
    )
    assert "error" in res


@pytest.mark.asyncio
async def test_add_item_archived_list_rejected(store):
    doc = await store.create_list("user-1", "Old List")
    await store.archive_list(doc["id"])

    req = _make_request(store)
    res = await execute_todo_add_item(
        {"agent_name": "atlas", "list_id": doc["id"], "text": "late entry",
         "owner_user_id": "user-1"},
        req,
    )
    assert "error" in res
    assert "archived" in res["error"]


@pytest.mark.asyncio
async def test_add_item_nonexistent_list_returns_error(store):
    req = _make_request(store)
    res = await execute_todo_add_item(
        {"agent_name": "atlas", "list_id": "nonexistent", "text": "hi",
         "owner_user_id": "user-1"},
        req,
    )
    assert "error" in res
    assert "not found" in res["error"]


# ------------------------------------------------------------- set_done tests

@pytest.mark.asyncio
async def test_owner_can_mark_item_done(store):
    doc = await store.create_list("user-1", "Build List")
    item = await store.add_item(doc["id"], "Ship feature", author="user-1")

    req = _make_request(store)
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": doc["id"], "item_id": item["id"],
         "done": True, "owner_user_id": "user-1"},
        req,
    )
    assert res.get("ok") is True
    assert res["done"] is True

    updated = await store.get_item(item["id"])
    assert updated["done"] is True

    # And it can be reopened.
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": doc["id"], "item_id": item["id"],
         "done": False, "owner_user_id": "user-1"},
        req,
    )
    assert res.get("ok") is True
    updated = await store.get_item(item["id"])
    assert updated["done"] is False


@pytest.mark.asyncio
async def test_non_owner_cannot_mark_done(store):
    doc = await store.create_list("user-1", "Read Only")
    item = await store.add_item(doc["id"], "A task", author="user-1")

    req = _make_request(store)
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": doc["id"], "item_id": item["id"],
         "done": True, "owner_user_id": "user-2"},
        req,
    )
    assert "error" in res
    assert "access" in res["error"]

    updated = await store.get_item(item["id"])
    assert updated["done"] is False


@pytest.mark.asyncio
async def test_set_done_rejects_item_from_another_list(store):
    doc_a = await store.create_list("user-1", "List A")
    doc_b = await store.create_list("user-1", "List B")
    foreign = await store.add_item(doc_b["id"], "Not yours", author="user-1")

    req = _make_request(store)
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": doc_a["id"], "item_id": foreign["id"],
         "done": True, "owner_user_id": "user-1"},
        req,
    )
    assert "error" in res
    assert "not found" in res["error"]

    updated = await store.get_item(foreign["id"])
    assert updated["done"] is False


@pytest.mark.asyncio
async def test_set_done_archived_list_rejected(store):
    doc = await store.create_list("user-1", "Old List")
    item = await store.add_item(doc["id"], "A task", author="user-1")
    await store.archive_list(doc["id"])

    req = _make_request(store)
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": doc["id"], "item_id": item["id"],
         "done": True, "owner_user_id": "user-1"},
        req,
    )
    assert "error" in res
    assert "archived" in res["error"]


@pytest.mark.asyncio
async def test_set_done_missing_or_bad_fields_returns_error(store):
    req = _make_request(store)

    # missing done
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": "d", "item_id": "i",
         "owner_user_id": "user-1"}, req
    )
    assert "error" in res
    # non-boolean done
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": "d", "item_id": "i",
         "done": "yes", "owner_user_id": "user-1"}, req
    )
    assert "error" in res
    # missing item_id
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": "d", "done": True,
         "owner_user_id": "user-1"}, req
    )
    assert "error" in res
    # missing owner_user_id
    res = await execute_todo_set_done(
        {"agent_name": "atlas", "list_id": "d", "item_id": "i", "done": True}, req
    )
    assert "error" in res
