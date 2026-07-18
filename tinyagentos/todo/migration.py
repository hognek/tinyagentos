"""Migrate kind=list documents from SharedDocsStore into TodoStore.

One-shot, idempotent migration. Run via the /api/todo/migrate endpoint
(admin-only) or called programmatically.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def migrate_list_docs(shared_docs_store, todo_store) -> dict:
    """Migrate all kind=list docs from shared_docs into todo lists.

    Reads every non-archived ``kind=list`` document, creates a corresponding
    todo list with the same owner/title, converts all entries into
    todo items (preserving order, text, done status, and author), then deletes
    the original doc + entries + members from shared_docs.

    Idempotent: if a matching todo list already exists for a source document
    (same owner + title), the source doc is simply cleaned up without creating
    a duplicate. This handles both re-runs and interrupted migrations where
    the target was created but the source was never deleted.

    Returns:
        dict with ``migrated`` (list count), ``items`` (total items moved),
        and ``lists`` (list of {old_id, new_id} pairs) for verification.
    """
    list_docs = await shared_docs_store.list_docs_by_kind("list")

    result = {"migrated": 0, "items": 0, "lists": []}

    for doc in list_docs:
        old_id = doc["id"]
        owner = doc["owner_user_id"]
        title = doc.get("title", "")
        entries = doc.get("entries", [])

        # Check for a pre-existing matching todo list (same owner + title).
        # This guards against duplicate creation on re-run or after an
        # interrupted migration where the target was created but the source
        # was never deleted.
        existing_lists = await todo_store.list_lists(
            owner, include_archived=True
        )
        matching = [l for l in existing_lists if l["title"] == title]

        if matching:
            new_id = matching[0]["id"]
            logger.info(
                "todo-migration: skipping already-migrated list %r "
                "(owner=%r, title=%r) → existing %r",
                old_id, owner, title, new_id,
            )
            result["lists"].append({"old_id": old_id, "new_id": new_id})
        else:
            todo_list = await todo_store.create_list(owner, title)
            new_id = todo_list["id"]

            # Convert entries to todo items in original order.
            for entry in entries:
                text = entry.get("text", "")
                done = bool(entry.get("done", False))
                author = entry.get("author", "")
                item = await todo_store.add_item(
                    new_id,
                    text,
                    author=author,
                )
                if done:
                    await todo_store.patch_item(item["id"], done=True)

            result["migrated"] += 1
            result["items"] += len(entries)
            result["lists"].append({"old_id": old_id, "new_id": new_id})

            logger.info(
                "todo-migration: migrated list %r → %r (%d items)",
                old_id,
                new_id,
                len(entries),
            )

        # Delete the original doc from shared_docs.
        await shared_docs_store.delete_doc(old_id)

    return result
