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

    Idempotent: newly created todo lists record the source document id in a
    ``migrated_from`` column.  On re-run each source doc is matched by its
    **exact** id rather than by owner+title alone, so two source docs that
    happen to share the same title are never conflated.

    Returns:
        dict with ``migrated`` (lists newly created), ``items`` (total items
        moved), and ``lists`` (list of {old_id, new_id} pairs) for verification.
    """
    list_docs = await shared_docs_store.list_docs_by_kind("list")

    result = {"migrated": 0, "items": 0, "lists": []}

    for doc in list_docs:
        old_id = doc["id"]
        owner = doc["owner_user_id"]
        title = doc.get("title", "")
        entries = doc.get("entries", [])

        existing_lists = await todo_store.list_lists(
            owner, include_archived=True
        )

        # -- primary idempotency check: exact source-doc match -----------
        # If a todo list already has migrated_from == old_id we know this
        # exact source was migrated on a previous run.
        migrated_match = [
            l for l in existing_lists
            if l.get("migrated_from") == old_id
        ]

        if migrated_match:
            new_id = migrated_match[0]["id"]
            logger.info(
                "todo-migration: skipping already-migrated doc %r "
                "(owner=%r, title=%r) → existing %r",
                old_id, owner, title, new_id,
            )
            result["lists"].append({"old_id": old_id, "new_id": new_id})
            # Clean up source doc (items already live in the target).
            await shared_docs_store.delete_doc(old_id)
            continue

        # -- fallback: owner+title match ---------------------------------
        # Handles interrupted migrations from code that predates the
        # migrated_from column.  The target list exists but was never
        # stamped, so we recover by flowing entries into it and stamping.
        title_match = [
            l for l in existing_lists
            if l["title"] == title and l.get("migrated_from") is None
        ]

        if title_match:
            new_id = title_match[0]["id"]
            logger.info(
                "todo-migration: recovering interrupted migration for "
                "doc %r (owner=%r, title=%r) → existing %r",
                old_id, owner, title, new_id,
            )
            # Flow entries into the existing list (data-loss prevention).
            for entry in entries:
                text = entry.get("text", "")
                done = bool(entry.get("done", False))
                author = entry.get("author", "")
                item = await todo_store.add_item(
                    new_id, text, author=author,
                )
                if done:
                    await todo_store.patch_item(item["id"], done=True)

            # Stamp so future re-runs take the primary check above.
            await todo_store.set_migrated_from(new_id, old_id)

            result["items"] += len(entries)
            result["lists"].append({"old_id": old_id, "new_id": new_id})
            # Clean up source doc.
            await shared_docs_store.delete_doc(old_id)
            continue

        # -- normal path: create a fresh todo list ------------------------
        todo_list = await todo_store.create_list(
            owner, title, migrated_from=old_id,
        )
        new_id = todo_list["id"]

        # Convert entries to todo items in original order.
        for entry in entries:
            text = entry.get("text", "")
            done = bool(entry.get("done", False))
            author = entry.get("author", "")
            item = await todo_store.add_item(
                new_id, text, author=author,
            )
            if done:
                await todo_store.patch_item(item["id"], done=True)

        result["migrated"] += 1
        result["items"] += len(entries)
        result["lists"].append({"old_id": old_id, "new_id": new_id})

        logger.info(
            "todo-migration: migrated list %r → %r (%d items)",
            old_id, new_id, len(entries),
        )

        # Delete the original doc from shared_docs.
        await shared_docs_store.delete_doc(old_id)

    return result
