# tinyagentos/routes/devices.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from tinyagentos.auth_context import CurrentUser, current_user

router = APIRouter()


class RegisterIn(BaseModel):
    platform: str
    display_name: str = ""
    push_token: str = ""

    @field_validator("platform")
    @classmethod
    def platform_supported(cls, v: str) -> str:
        if v not in ("ios", "watchos"):
            raise ValueError("platform must be 'ios' or 'watchos'")
        return v


class PushTokenIn(BaseModel):
    push_token: str


@router.post("/api/devices/register")
async def register_device(
    body: RegisterIn, request: Request, user: CurrentUser = Depends(current_user)
):
    store = request.app.state.device_store
    device = await store.register(
        user_id=user.user_id,
        platform=body.platform,
        push_token=body.push_token,
        display_name=body.display_name,
    )
    return device  # includes scoped_token, the only time it is returned


@router.get("/api/devices")
async def list_devices(request: Request, user: CurrentUser = Depends(current_user)):
    store = request.app.state.device_store
    return {"items": await store.list_for_user(user.user_id)}


async def _owned_or_404(store, device_id: str, user: CurrentUser):
    # Devices are strictly personal: each holds a per-device scoped token and
    # its owner's sensor grants. Unlike system Decisions, there is NO admin
    # bypass here, so even an admin session manages only its own devices through
    # these self-service routes (a compromised admin cannot hijack a user's
    # device or its grants). Admin device management, if ever needed, is a
    # separate surface.
    device = await store.get(device_id)
    if device is None or device["revoked"] or device["user_id"] != user.user_id:
        return None
    return device


@router.patch("/api/devices/{device_id}/push-token")
async def update_push_token(
    device_id: str, body: PushTokenIn, request: Request,
    user: CurrentUser = Depends(current_user),
):
    store = request.app.state.device_store
    if await _owned_or_404(store, device_id, user) is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    updated = await store.update_push_token(device_id, body.push_token)
    updated.pop("scoped_token", None)
    return updated


@router.delete("/api/devices/{device_id}")
async def revoke_device(
    device_id: str, request: Request, user: CurrentUser = Depends(current_user)
):
    store = request.app.state.device_store
    if await _owned_or_404(store, device_id, user) is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    await store.revoke(device_id)
    return {"revoked": True}
