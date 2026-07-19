"""Todo list REST API.

Todo lists are owned by a single user. Items are ordered by position
and can have optional due dates and reminders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tinyagentos.auth_context import CurrentUser, current_user

router = APIRouter()


# --------------------------------------------------------------------- models

class CreateTodoListIn(BaseModel):
    title: str = ""


class PatchTodoListIn(BaseModel):
    title: str | None = None
    archived: bool | None = None


class AddTodoItemIn(BaseModel):
    text: str = Field(..., min_length=1)
    due_at: str | None = None
    remind_at: str | None = None


class PatchTodoItemIn(BaseModel):
    text: str | None = None
    done: bool | None = None
    due_at: str | None = None
    remind_at: str | None = None


class ReorderEntry(BaseModel):
    id: str
    position: int


class ReorderItemsIn(BaseModel):
    items: list[ReorderEntry]


# -------------------------------------------------------------------- helpers

def _get_store(request: Request):
    return request.app.state.todo_store


def _check_owner(doc: dict, user: CurrentUser):
    """Return a 403 JSONResponse if the caller does not own the list, else None."""
    if not user.is_admin and doc["owner_user_id"] != user.user_id:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return None


# ----------------------------------------------------------------- list routes

@router.get("/api/todo")
async def list_lists(
    request: Request,
    include_archived: bool = False,
    user: CurrentUser = Depends(current_user),
):
    store = _get_store(request)
    return await store.list_lists(user.user_id, include_archived=include_archived)


@router.post("/api/todo")
async def create_list(
    body: CreateTodoListIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    store = _get_store(request)
    return await store.create_list(user.user_id, body.title)


@router.get("/api/todo/{list_id}")
async def get_list(
    list_id: str,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    store = _get_store(request)
    doc = await store.get_list(list_id)
    if doc is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    err = _check_owner(doc, user)
    if err:
        return err
    return doc


@router.patch("/api/todo/{list_id}")
async def patch_list(
    list_id: str,
    body: PatchTodoListIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    store = _get_store(request)
    doc = await store.get_list(list_id)
    if doc is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    err = _check_owner(doc, user)
    if err:
        return err
    if body.title is not None:
        await store.set_title(list_id, body.title)
    if body.archived is True:
        await store.archive_list(list_id)
    elif body.archived is False:
        await store.unarchive_list(list_id)
    return await store.get_list(list_id)


# ---------------------------------------------------------------- item routes

@router.post("/api/todo/{list_id}/items")
async def add_item(
    list_id: str,
    body: AddTodoItemIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    store = _get_store(request)
    doc = await store.get_list(list_id)
    if doc is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    err = _check_owner(doc, user)
    if err:
        return err

    from datetime import datetime, timezone

    due_at = None
    if body.due_at:
        try:
            dt = datetime.fromisoformat(body.due_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            due_at = dt.timestamp()
        except ValueError:
            return JSONResponse(
                {"error": f"invalid due_at: {body.due_at!r}"}, status_code=400
            )
    remind_at = None
    if body.remind_at:
        try:
            dt = datetime.fromisoformat(body.remind_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            remind_at = dt.timestamp()
        except ValueError:
            return JSONResponse(
                {"error": f"invalid remind_at: {body.remind_at!r}"}, status_code=400
            )

    return await store.add_item(
        list_id, body.text, author=user.user_id, due_at=due_at, remind_at=remind_at
    )


@router.patch("/api/todo/{list_id}/items/{item_id}")
async def patch_item(
    list_id: str,
    item_id: str,
    body: PatchTodoItemIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    store = _get_store(request)
    doc = await store.get_list(list_id)
    if doc is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    err = _check_owner(doc, user)
    if err:
        return err

    item = await store.get_item(item_id)
    if item is None:
        return JSONResponse({"error": "item not found"}, status_code=404)
    if item["list_id"] != list_id:
        return JSONResponse({"error": "item not in list"}, status_code=404)

    from datetime import datetime, timezone

    _CLEAR_SENTINEL = -1.0

    def _parse_ts(val):
        """None = no change, '' = clear, ISO str = set."""
        if val is None:
            return None  # not sent
        if val == "":
            return _CLEAR_SENTINEL
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None  # Will be handled below

    due_at = _parse_ts(body.due_at)
    if due_at is None and body.due_at is not None and body.due_at != "":
        return JSONResponse(
            {"error": f"invalid due_at: {body.due_at!r}"}, status_code=400
        )

    remind_at = _parse_ts(body.remind_at)
    if remind_at is None and body.remind_at is not None and body.remind_at != "":
        return JSONResponse(
            {"error": f"invalid remind_at: {body.remind_at!r}"}, status_code=400
        )

    kwargs = {}
    if body.text is not None:
        kwargs["text"] = body.text
    if body.done is not None:
        kwargs["done"] = body.done
    if body.due_at is not None:
        kwargs["due_at"] = None if due_at == _CLEAR_SENTINEL else due_at
    if body.remind_at is not None:
        kwargs["remind_at"] = None if remind_at == _CLEAR_SENTINEL else remind_at

    return await store.patch_item(item_id, **kwargs)


@router.delete("/api/todo/{list_id}/items/{item_id}")
async def delete_item(
    list_id: str,
    item_id: str,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    store = _get_store(request)
    doc = await store.get_list(list_id)
    if doc is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    err = _check_owner(doc, user)
    if err:
        return err

    item = await store.get_item(item_id)
    if item is None:
        return JSONResponse({"error": "item not found"}, status_code=404)
    if item["list_id"] != list_id:
        return JSONResponse({"error": "item not in list"}, status_code=404)

    await store.delete_item(item_id)
    return JSONResponse({"ok": True})


@router.put("/api/todo/{list_id}/items/reorder")
async def reorder_items(
    list_id: str,
    body: ReorderItemsIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    store = _get_store(request)
    doc = await store.get_list(list_id)
    if doc is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    err = _check_owner(doc, user)
    if err:
        return err

    items = [{"id": e.id, "position": e.position} for e in body.items]
    await store.reorder_items(list_id, items)
    return JSONResponse({"ok": True})
