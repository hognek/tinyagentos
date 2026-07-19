"""Agent-side tools for todo lists.

Lets an agent list the todo lists it has access to, append items, and
toggle completion. The loop guard (skip_agent) prevents the writing agent
from being notified about its own write.
"""

from __future__ import annotations

import logging

from fastapi import Request

logger = logging.getLogger(__name__)


async def execute_todo_list_lists(args: dict, request: Request) -> dict:
    """List non-archived todo lists the calling agent has access to."""
    args = args or {}
    agent_name = args.get("agent_name")
    if not agent_name or not isinstance(agent_name, str):
        return {"error": "todo_list_lists requires an 'agent_name' string"}

    owner_user_id = args.get("owner_user_id")
    if not owner_user_id or not isinstance(owner_user_id, str):
        return {"error": "todo_list_lists requires an 'owner_user_id' string"}

    try:
        store = request.app.state.todo_store
        lists = await store.list_lists(owner_user_id)
        return {"lists": lists}
    except Exception as exc:
        return {"error": str(exc)}


async def execute_todo_add_item(args: dict, request: Request) -> dict:
    """Append an item to a todo list the calling agent has access to.

    The agent must have access to the list (owner match).
    """
    args = args or {}
    agent_name = args.get("agent_name")
    list_id = args.get("list_id")
    text = args.get("text")
    owner_user_id = args.get("owner_user_id")

    if not agent_name or not isinstance(agent_name, str):
        return {"error": "todo_add_item requires an 'agent_name' string"}
    if not list_id or not isinstance(list_id, str):
        return {"error": "todo_add_item requires a 'list_id' string"}
    if not isinstance(text, str) or not text:
        return {"error": "todo_add_item requires a 'text' string"}
    if not owner_user_id or not isinstance(owner_user_id, str):
        return {"error": "todo_add_item requires an 'owner_user_id' string"}

    try:
        store = request.app.state.todo_store

        doc = await store.get_list(list_id)
        if doc is None:
            return {"error": "list not found"}
        if doc.get("archived_at") is not None:
            return {"error": "list is archived"}
        if doc.get("owner_user_id") != owner_user_id:
            return {"error": "agent does not have access to this list"}

        item = await store.add_item(list_id, text, author=agent_name)

        try:
            from tinyagentos.todo.notify import _trigger_todo_agent_notifications

            await _trigger_todo_agent_notifications(
                request, doc, text, skip_agent=agent_name
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("todo_add_item: agent trigger failed: %s", exc)

        return {"ok": True, "item_id": item["id"]}
    except Exception as exc:
        return {"error": str(exc)}


async def execute_todo_set_done(args: dict, request: Request) -> dict:
    """Mark a todo item done (or not done) on a list the agent has access to.

    The agent must have access to the list (owner match) and the item must
    belong to the named list.
    """
    args = args or {}
    agent_name = args.get("agent_name")
    list_id = args.get("list_id")
    item_id = args.get("item_id")
    done = args.get("done")
    owner_user_id = args.get("owner_user_id")

    if not agent_name or not isinstance(agent_name, str):
        return {"error": "todo_set_done requires an 'agent_name' string"}
    if not list_id or not isinstance(list_id, str):
        return {"error": "todo_set_done requires a 'list_id' string"}
    if not item_id or not isinstance(item_id, str):
        return {"error": "todo_set_done requires an 'item_id' string"}
    if not isinstance(done, bool):
        return {"error": "todo_set_done requires a boolean 'done'"}
    if not owner_user_id or not isinstance(owner_user_id, str):
        return {"error": "todo_set_done requires an 'owner_user_id' string"}

    try:
        store = request.app.state.todo_store

        doc = await store.get_list(list_id)
        if doc is None:
            return {"error": "list not found"}
        if doc.get("archived_at") is not None:
            return {"error": "list is archived"}
        if doc.get("owner_user_id") != owner_user_id:
            return {"error": "agent does not have access to this list"}

        # Confine the agent to items of the list it actually belongs to.
        if not any(i.get("id") == item_id for i in doc.get("items", [])):
            return {"error": "item not found in this list"}

        await store.patch_item(item_id, done=done)
        return {"ok": True, "item_id": item_id, "done": done}
    except Exception as exc:
        return {"error": str(exc)}
