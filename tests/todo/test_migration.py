"""Tests for the kind=list → Todo migration."""

from __future__ import annotations

import pytest
import pytest_asyncio

from tinyagentos.notes.shared_docs_store import SharedDocsStore
from tinyagentos.todo.todo_store import TodoStore
from tinyagentos.todo.migration import migrate_list_docs


@pytest_asyncio.fixture
async def shared_store(tmp_path):
    s = SharedDocsStore(tmp_path / "shared_docs.db")
    await s.init()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def todo_store(tmp_path):
    s = TodoStore(tmp_path / "todo.db")
    await s.init()
    yield s
    await s.close()


# -------------------------------------------------------------------- helpers

async def _setup_list_doc(store, owner, title, entries, done_mask=None):
    """Create a kind=list doc with entries. done_mask is a set of indices."""
    doc = await store.create_doc(owner, "list", title)
    created = []
    for i, text in enumerate(entries):
        entry = await store.add_entry(doc["id"], text, author=owner)
        if done_mask and i in done_mask:
            await store.set_entry_done(entry["id"], True)
        created.append(entry)
    return doc, created


# --------------------------------------------------------------------- tests

@pytest.mark.asyncio
async def test_migrate_empty(shared_store, todo_store):
    """No list docs → zero migrated, idempotent."""
    result = await migrate_list_docs(shared_store, todo_store)
    assert result["migrated"] == 0
    assert result["items"] == 0
    assert result["lists"] == []

    # Idempotent re-run.
    result2 = await migrate_list_docs(shared_store, todo_store)
    assert result2 == result


@pytest.mark.asyncio
async def test_migrate_single_list(shared_store, todo_store):
    """Single list with entries → migrated, source deleted."""
    doc, entries = await _setup_list_doc(
        shared_store, "user-a", "Groceries",
        ["Milk", "Eggs", "Bread"],
        done_mask={1},
    )

    result = await migrate_list_docs(shared_store, todo_store)
    assert result["migrated"] == 1
    assert result["items"] == 3
    assert len(result["lists"]) == 1
    assert result["lists"][0]["old_id"] == doc["id"]

    new_id = result["lists"][0]["new_id"]

    # Source should be gone.
    assert await shared_store.get_doc(doc["id"]) is None

    # Target should have the list + items.
    todo_list = await todo_store.get_list(new_id)
    assert todo_list is not None
    assert todo_list["owner_user_id"] == "user-a"
    assert todo_list["title"] == "Groceries"
    assert todo_list["archived_at"] is None

    items = todo_list["items"]
    assert len(items) == 3
    assert [i["text"] for i in items] == ["Milk", "Eggs", "Bread"]
    assert [i["done"] for i in items] == [False, True, False]
    assert [i["author"] for i in items] == ["user-a", "user-a", "user-a"]


@pytest.mark.asyncio
async def test_migrate_multiple_lists(shared_store, todo_store):
    """Multiple list docs from different owners → all migrated."""
    doc1, _ = await _setup_list_doc(
        shared_store, "alice", "Weekend",
        ["Clean", "Cook"],
    )
    doc2, _ = await _setup_list_doc(
        shared_store, "bob", "Work",
        ["Report", "Slides", "Email"],
        done_mask={0},
    )

    result = await migrate_list_docs(shared_store, todo_store)
    assert result["migrated"] == 2
    assert result["items"] == 5

    # Both sources deleted.
    assert await shared_store.get_doc(doc1["id"]) is None
    assert await shared_store.get_doc(doc2["id"]) is None

    # Verify data integrity by mapping.
    by_old = {item["old_id"]: item for item in result["lists"]}
    list1 = await todo_store.get_list(by_old[doc1["id"]]["new_id"])
    list2 = await todo_store.get_list(by_old[doc2["id"]]["new_id"])

    assert list1["owner_user_id"] == "alice"
    assert list1["title"] == "Weekend"
    assert [i["text"] for i in list1["items"]] == ["Clean", "Cook"]

    assert list2["owner_user_id"] == "bob"
    assert list2["title"] == "Work"
    assert [i["text"] for i in list2["items"]] == ["Report", "Slides", "Email"]
    assert [i["done"] for i in list2["items"]] == [True, False, False]


@pytest.mark.asyncio
async def test_migrate_skips_notes(shared_store, todo_store):
    """kind=note docs are left untouched by the migration."""
    note = await shared_store.create_doc("user-a", "note", "Ideas")
    await shared_store.add_entry(note["id"], "AI todo app", author="user-a")

    list_doc, _ = await _setup_list_doc(
        shared_store, "user-a", "Tasks",
        ["Do the thing"],
    )

    result = await migrate_list_docs(shared_store, todo_store)
    assert result["migrated"] == 1
    assert result["items"] == 1

    # Note should still exist.
    still_note = await shared_store.get_doc(note["id"])
    assert still_note is not None
    assert still_note["kind"] == "note"
    assert len(still_note["entries"]) == 1
    assert still_note["entries"][0]["text"] == "AI todo app"

    # List should be gone.
    assert await shared_store.get_doc(list_doc["id"]) is None


@pytest.mark.asyncio
async def test_migrate_archived_list_not_migrated(shared_store, todo_store):
    """Archived list docs are excluded from migration."""
    doc, _ = await _setup_list_doc(
        shared_store, "user-a", "Old tasks",
        ["Thing 1"],
    )
    await shared_store.archive_doc(doc["id"])

    result = await migrate_list_docs(shared_store, todo_store)
    assert result["migrated"] == 0
    assert result["items"] == 0

    # Archived doc still exists.
    still_doc = await shared_store.get_doc(doc["id"])
    assert still_doc is not None
    assert still_doc["archived_at"] is not None


@pytest.mark.asyncio
async def test_migrate_idempotent(shared_store, todo_store):
    """Running migration twice should be safe — second call is a no-op."""
    await _setup_list_doc(
        shared_store, "user-a", "Tasks",
        ["A", "B", "C"],
    )

    r1 = await migrate_list_docs(shared_store, todo_store)
    assert r1["migrated"] == 1
    assert r1["items"] == 3

    # Second run — nothing left to migrate.
    r2 = await migrate_list_docs(shared_store, todo_store)
    assert r2["migrated"] == 0
    assert r2["items"] == 0

    # Data still intact in todo store.
    new_id = r1["lists"][0]["new_id"]
    todo_list = await todo_store.get_list(new_id)
    assert todo_list is not None
    assert len(todo_list["items"]) == 3


@pytest.mark.asyncio
async def test_migrate_preserves_done_and_order(shared_store, todo_store):
    """Done flags and entry order are faithfully migrated."""
    doc, entries = await _setup_list_doc(
        shared_store, "user-a", "Checklist",
        ["First", "Second", "Third", "Fourth"],
        done_mask={0, 3},  # First and Fourth are done
    )

    result = await migrate_list_docs(shared_store, todo_store)
    new_id = result["lists"][0]["new_id"]
    todo_list = await todo_store.get_list(new_id)

    items = todo_list["items"]
    assert [i["text"] for i in items] == ["First", "Second", "Third", "Fourth"]
    assert [i["done"] for i in items] == [True, False, False, True]
    assert [i["author"] for i in items] == ["user-a"] * 4
