from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Protocol

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils

logger = logging.getLogger(__name__)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class ApnsSender(Protocol):
    async def send(self, push_token: str, payload: dict, *, topic: str | None = None) -> bool:
        ...


class NullApnsSender:
    """Used when APNs is unconfigured: logs the intent and reports failure so
    callers treat the device as unreachable rather than assuming delivery."""

    async def send(self, push_token: str, payload: dict, *, topic: str | None = None) -> bool:
        logger.info("APNs not configured; dropping push to %s", push_token[:8])
        return False


def build_apns_payload(
    *, title: str, body: str, data: dict | None = None, content_available: bool = False
) -> dict:
    aps: dict = {}
    if title or body:
        aps["alert"] = {"title": title, "body": body}
    if content_available:
        aps["content-available"] = 1
    payload = {"aps": aps}
    if data:
        payload.update(data)
    return payload


def build_apns_jwt(*, key_pem: str, key_id: str, team_id: str, now: int) -> str:
    header = {"alg": "ES256", "kid": key_id}
    claims = {"iss": team_id, "iat": now}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    der_sig = key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = asym_utils.decode_dss_signature(der_sig)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return signing_input + "." + _b64url(raw_sig)


class HttpApnsSender:
    def __init__(
        self, *, key_pem: str, key_id: str, team_id: str, bundle_id: str,
        host: str = "api.push.apple.com", client: httpx.AsyncClient | None = None,
    ):
        self._key_pem = key_pem
        self._key_id = key_id
        self._team_id = team_id
        self._bundle_id = bundle_id
        self._host = host
        self._client = client or httpx.AsyncClient(http2=True)

    async def send(self, push_token: str, payload: dict, *, topic: str | None = None) -> bool:
        jwt = build_apns_jwt(
            key_pem=self._key_pem, key_id=self._key_id,
            team_id=self._team_id, now=int(time.time()),
        )
        try:
            resp = await self._client.post(
                f"https://{self._host}/3/device/{push_token}",
                headers={
                    "authorization": f"bearer {jwt}",
                    "apns-topic": topic or self._bundle_id,
                    "apns-push-type": "background" if payload.get("aps", {}).get(
                        "content-available"
                    ) else "alert",
                },
                content=json.dumps(payload),
            )
        except httpx.HTTPError:
            logger.warning("APNs send failed for %s", push_token[:8], exc_info=True)
            return False
        return resp.status_code == 200


def apns_sender_from_env() -> ApnsSender:
    key_id = os.environ.get("TAOS_APNS_KEY_ID")
    team_id = os.environ.get("TAOS_APNS_TEAM_ID")
    bundle_id = os.environ.get("TAOS_APNS_BUNDLE_ID")
    key_path = os.environ.get("TAOS_APNS_KEY_PATH")
    if key_id and team_id and bundle_id and key_path and os.path.isfile(key_path):
        with open(key_path) as fh:
            key_pem = fh.read()
        return HttpApnsSender(
            key_pem=key_pem, key_id=key_id, team_id=team_id, bundle_id=bundle_id
        )
    return NullApnsSender()
