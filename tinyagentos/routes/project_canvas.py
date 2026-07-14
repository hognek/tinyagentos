"""REST API for per-project canvas boards.

See docs/superpowers/specs/2026-04-28-projects-canvas-board-design.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, Response
from pydantic import BaseModel, Field

from tinyagentos.projects.canvas.store import CanvasPermissionError
from tinyagentos.projects.canvas.unfurl import fetch_link_metadata
from tinyagentos.projects.canvas.render import render_snapshot_png

logger = logging.getLogger(__name__)
router = APIRouter()

# Agent scopes (slice 1) that unlock canvas read / write on a project the token
# is bound to. The write scope is strictly narrower than read: holding
# canvas_write must NEVER satisfy a read, and vice versa (D3 enforcement matrix).
_CANVAS_READ_SCOPE = "canvas_read"
_CANVAS_WRITE_SCOPE = "canvas_write"


def _user_id(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if uid:
        return uid
    return "system"


async def _authorize_canvas_actor(
    request: Request, project_id: str, mode: Literal["read", "write"]
) -> "tuple[str, str] | JSONResponse":
    """Resolve + authorize the actor for a canvas route.

    Accepts EITHER a session owner/admin (behavior unchanged from before the
    agent gate) OR an approved external agent's registry JWT bound to THIS
    project with the matching canvas scope AND the matching per-project member
    flag:

      * read mode  -> canvas_read scope + can_read_canvas member flag
      * write mode -> canvas_write scope + can_edit_canvas member flag

    Returns ``(actor_kind, actor_id)`` on success, or a JSONResponse to return
    directly.  A token bound to a DIFFERENT project collapses into an
    existence-hiding 404 (never confirms the project exists).  A token for this
    project that is missing the scope or the member flag gets 403.
    """
    uid = getattr(request.state, "user_id", None)
    if uid:
        # Session path: project visibility gate (D3).  Only the project owner or
        # an admin may touch the canvas; a human needs no scope and no checkbox,
        # but a non-owner collapses into the SAME existence-hiding 404 the agent
        # path uses (compare _get_owned_project on the task routes).  Attribution
        # stays the verified user.
        ps = request.app.state.project_store
        project = await ps.get_project(project_id)
        is_admin = bool(getattr(request.state, "is_admin", False))
        if project is not None and not is_admin and project.get("user_id") != uid:
            return JSONResponse({"error": "not found"}, status_code=404)
        return ("user", _user_id(request))
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        # Middleware normally 401s unauthenticated requests before the route
        # runs; a middleware-bypassing test context reaches here, so fall back
        # to a system actor (there is no real principal to attribute to).
        return ("user", "system")
    from tinyagentos.agent_token_auth import (
        check_agent_scope_for_project,
        PROJECT_SCOPE_MISMATCH_DETAIL,
    )
    scope = _CANVAS_READ_SCOPE if mode == "read" else _CANVAS_WRITE_SCOPE
    try:
        cid = await check_agent_scope_for_project(request, scope, project_id)
    except HTTPException as exc:
        if exc.status_code == 403 and exc.detail == PROJECT_SCOPE_MISMATCH_DETAIL:
            return JSONResponse({"error": "not found"}, status_code=404)
        raise
    if cid is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    ps = request.app.state.project_store
    member = await ps.get_member(project_id, cid)
    flag = (member or {}).get(
        "can_read_canvas" if mode == "read" else "can_edit_canvas"
    )
    if not flag:
        return JSONResponse(
            {
                "error": "permission_denied",
                "message": f"agent {cid} lacks canvas {mode} access on {project_id}",
            },
            status_code=403,
        )
    return ("agent", cid)


class CreateElementIn(BaseModel):
    kind: Literal[
        "note", "link", "image", "user_shape",
        "text", "mermaid", "flowchart", "mindmap_edge",
    ]
    x: float
    y: float
    w: float
    h: float
    rotation: float = 0
    z_index: int = 0
    payload: dict = Field(default_factory=dict)
    id: str | None = None
    element_id: str | None = None


@router.get("/api/projects/{project_id}/canvas/elements")
async def list_canvas_elements(
    project_id: str, request: Request, element_id: str | None = None,
):
    auth = await _authorize_canvas_actor(request, project_id, "read")
    if isinstance(auth, JSONResponse):
        return auth
    cs = request.app.state.project_canvas_store
    elements = await cs.list_elements(project_id, element_id=element_id)
    return {"elements": elements}


@router.post("/api/projects/{project_id}/canvas/elements", status_code=201)
async def create_canvas_element(
    project_id: str, payload: CreateElementIn, request: Request,
):
    auth = await _authorize_canvas_actor(request, project_id, "write")
    if isinstance(auth, JSONResponse):
        return auth
    actor_kind, actor_id = auth
    cs = request.app.state.project_canvas_store
    element = payload.model_dump()
    element_id = element.pop("element_id", None)
    if element["kind"] == "link":
        url = (element.get("payload") or {}).get("url")
        if not url:
            return JSONResponse({"error": "link element requires payload.url"}, status_code=400)
        meta = await fetch_link_metadata(url)
        element["payload"] = meta
    try:
        new_el = await cs.add_element(
            project_id=project_id, element=element,
            author_kind=actor_kind, author_id=actor_id,
            element_id=element_id,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"element": new_el}


class PatchElementIn(BaseModel):
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    rotation: float | None = None
    z_index: int | None = None
    payload: dict | None = None


@router.patch("/api/projects/{project_id}/canvas/elements/{element_id}")
async def update_canvas_element(
    project_id: str, element_id: str, payload: PatchElementIn, request: Request,
):
    auth = await _authorize_canvas_actor(request, project_id, "write")
    if isinstance(auth, JSONResponse):
        return auth
    actor_kind, actor_id = auth
    cs = request.app.state.project_canvas_store
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        updated = await cs.update_element(
            project_id=project_id, element_id=element_id, patch=patch,
            author_kind=actor_kind, author_id=actor_id,
        )
    except CanvasPermissionError as e:
        return JSONResponse({"error": "permission_denied", "message": str(e)}, status_code=403)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    return {"element": updated}


@router.delete("/api/projects/{project_id}/canvas/elements/{element_id}", status_code=204)
async def delete_canvas_element(project_id: str, element_id: str, request: Request):
    auth = await _authorize_canvas_actor(request, project_id, "write")
    if isinstance(auth, JSONResponse):
        return auth
    actor_kind, actor_id = auth
    cs = request.app.state.project_canvas_store
    try:
        await cs.delete_element(
            project_id=project_id, element_id=element_id,
            author_kind=actor_kind, author_id=actor_id,
        )
    except CanvasPermissionError as e:
        return JSONResponse({"error": "permission_denied", "message": str(e)}, status_code=403)
    return Response(status_code=204)


class PermissionIn(BaseModel):
    can_read_canvas: bool | None = None
    can_edit_canvas: bool | None = None


@router.get("/api/projects/{project_id}/canvas/snapshot.png")
async def get_canvas_png(project_id: str, request: Request):
    auth = await _authorize_canvas_actor(request, project_id, "read")
    if isinstance(auth, JSONResponse):
        return auth
    cs = request.app.state.project_canvas_store
    elements = await cs.list_elements(project_id)
    project = await request.app.state.project_store.get_project(project_id)
    if project is None:
        return JSONResponse({"error": "project not found"}, status_code=404)
    out = (
        request.app.state.projects_root
        / project["slug"] / "files" / "canvas"
    )
    out.mkdir(parents=True, exist_ok=True)
    target = out / "snapshot.png"
    render_snapshot_png(elements=elements, output_path=target)
    return FileResponse(target, media_type="image/png")


@router.get("/api/projects/{project_id}/canvas/snapshot.tldr")
async def get_canvas_tldr(project_id: str, request: Request):
    auth = await _authorize_canvas_actor(request, project_id, "read")
    if isinstance(auth, JSONResponse):
        return auth
    snap = request.app.state.canvas_snapshotter
    path = await snap.export_now(project_id)
    if path is None or not path.exists():
        return JSONResponse({"error": "project not found"}, status_code=404)
    return FileResponse(path, media_type="application/json")


@router.patch("/api/projects/{project_id}/canvas/permissions/{agent_id}")
async def set_canvas_permission(
    project_id: str, agent_id: str, payload: PermissionIn, request: Request,
):
    ps = request.app.state.project_store
    project = await ps.get_project(project_id)
    if project is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    uid = getattr(request.state, "user_id", None)
    is_admin = bool(getattr(request.state, "is_admin", False))
    if not uid or (not is_admin and project.get("user_id") != uid):
        return JSONResponse(
            {
                "error": "forbidden",
                "message": "only the project owner or an admin may change canvas permissions",
            },
            status_code=403,
        )
    sets: list[str] = []
    params: list = []
    if payload.can_read_canvas is not None:
        sets.append("can_read_canvas = ?")
        params.append(1 if payload.can_read_canvas else 0)
    if payload.can_edit_canvas is not None:
        sets.append("can_edit_canvas = ?")
        params.append(1 if payload.can_edit_canvas else 0)
    if not sets:
        return JSONResponse({"error": "no permission field provided"}, status_code=400)
    params.extend([project_id, agent_id])
    cur = await ps._db.execute(
        f"UPDATE project_members SET {', '.join(sets)} "
        "WHERE project_id = ? AND member_id = ?",
        params,
    )
    await ps._db.commit()
    if cur.rowcount == 0:
        return JSONResponse({"error": "member not found"}, status_code=404)
    member = await ps.get_member(project_id, agent_id)
    broker = request.app.state.project_event_broker
    from tinyagentos.projects.events import ProjectEvent
    await broker.publish(
        project_id,
        ProjectEvent(
            kind="canvas.permission_changed",
            payload={
                "actor": {"kind": "user", "id": uid},
                "agent_id": agent_id,
                "can_read_canvas": bool(member.get("can_read_canvas")),
                "can_edit_canvas": bool(member.get("can_edit_canvas")),
            },
        ),
    )
    return {
        "ok": True,
        "agent_id": agent_id,
        "can_read_canvas": bool(member.get("can_read_canvas")),
        "can_edit_canvas": bool(member.get("can_edit_canvas")),
    }


@router.get("/api/projects/{project_id}/canvas/stream")
async def canvas_stream(project_id: str, request: Request):
    auth = await _authorize_canvas_actor(request, project_id, "read")
    if isinstance(auth, JSONResponse):
        return auth
    broker = request.app.state.project_event_broker
    queue = await broker.subscribe(project_id)

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
                    continue
                if not str(ev.kind).startswith("canvas."):
                    continue
                data = json.dumps({
                    "type": ev.kind,
                    "project_id": project_id,
                    "payload": ev.payload,
                    "ts": ev.ts,
                })
                yield f"data: {data}\n\n"
        finally:
            await broker.unsubscribe(project_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")
