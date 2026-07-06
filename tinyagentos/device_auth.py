from __future__ import annotations

import time

from fastapi import HTTPException, Request

# Only refresh last_seen at most once a minute per device so authenticating on
# every request does not turn auth into a per-request DB write (write
# amplification / a DoS-on-the-DB surface).
_TOUCH_INTERVAL_S = 60


def extract_bearer(request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    # RFC 6750: the auth scheme name is case-insensitive.
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


async def require_device(request: Request) -> dict:
    """FastAPI dependency: authenticate the caller as a registered device by
    its scoped token. 401 if the header is missing or the token is unknown or
    revoked. Refreshes last_seen (debounced) on success."""
    token = extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="device token required")
    store = request.app.state.device_store
    device = await store.get_by_token(token)
    if device is None:
        raise HTTPException(status_code=401, detail="invalid device token")
    if time.time() - device["last_seen"] > _TOUCH_INTERVAL_S:
        await store.touch(device["device_id"])
    return device
