from __future__ import annotations

from fastapi import HTTPException, Request


def extract_bearer(request) -> str | None:
    header = request.headers.get("authorization")
    if not header or not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    return token or None


async def require_device(request: Request) -> dict:
    """FastAPI dependency: authenticate the caller as a registered device by
    its scoped token. 401 if the header is missing or the token is unknown or
    revoked. Touches last_seen on success."""
    token = extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="device token required")
    store = request.app.state.device_store
    device = await store.get_by_token(token)
    if device is None:
        raise HTTPException(status_code=401, detail="invalid device token")
    await store.touch(device["device_id"])
    return device
