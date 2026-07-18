"""Ed25519-signed envelopes and peer-token auth for the peer channel.

Reuses ``tinyagentos.hub.identity`` for key material: the node's own Ed25519
signing key signs every outgoing envelope; incoming envelopes are verified
against the sender's pinned public key from the contacts store.

Peer tokens are minted by the owning instance and presented by the remote
instance as ``Authorization: Bearer <peer-token>`` on ``POST /api/peer/*``.
They are opaque hex strings, hashed at rest in the peer_links table (same
pattern as registry tokens).  The ``sub`` concept is ``contact:{username}``
and peer tokens grant *only* the peer route family — never the general API.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Optional

from tinyagentos.hub.identity import (
    sign as _sign,
    verify_signature,
)


# ---------------------------------------------------------------------------
# Signed envelopes
# ---------------------------------------------------------------------------

def build_envelope(
    *,
    from_username: str,
    to_username: str,
    kind: str,
    body: dict | None = None,
) -> dict:
    """Build a signed envelope from this node to a remote contact.

    ``kind`` is one of: ``handshake``, ``collab_invite``, ``delegation_request``,
    ``chat``, ``ack``.  ``body`` is the payload dict.

    The envelope is signed with this node's Ed25519 signing key (from
    ``hub.identity``), so the receiver can verify it against the pinned pubkey
    from the contacts store (trust-on-first-use at friend-accept).

    Envelope shape::

        {
            "from": "hub:jaylfc",
            "to":   "hub:hogne",
            "kind": "collab_invite",
            "body": { ... },
            "ts":   1710000000.0,
            "nonce": "hex...",
            "sig":   "hex..."
        }
    """
    import secrets

    nonce = secrets.token_hex(16)
    ts = time.time()
    envelope: dict = {
        "from": f"hub:{from_username}",
        "to": f"hub:{to_username}",
        "kind": kind,
        "ts": ts,
        "nonce": nonce,
    }
    if body is not None:
        envelope["body"] = body

    # Sign the canonical JSON representation (sorted keys, compact).
    payload = _canonical_json(envelope)
    sig = _sign(payload)
    envelope["sig"] = sig
    return envelope


def verify_envelope(
    envelope: dict,
    *,
    expected_kind: str | None = None,
    max_age_seconds: float = 300.0,
) -> tuple[bool, str]:
    """Verify a signed envelope against the sender's pinned Ed25519 pubkey.

    Returns ``(ok, error_reason)``.  ``ok`` is True only when all checks pass.
    The caller MUST have already resolved the sender's pubkey from the contacts
    store before calling this function.

    Checks performed:
    1. Required fields present (from, to, kind, ts, nonce, sig).
    2. Timestamp is within ``max_age_seconds`` of now (replay window).
    3. ``expected_kind`` matches if provided.
    4. Signature verifies against the sender's pubkey.
    """
    required = ("from", "to", "kind", "ts", "nonce", "sig")
    for field in required:
        if field not in envelope:
            return False, f"missing required field: {field}"

    # Timestamp freshness (with 30s clock-skew grace).
    age = abs(time.time() - envelope["ts"])
    if age > max_age_seconds + 30.0:
        return False, f"envelope too old: {age:.0f}s > {max_age_seconds}s"

    if expected_kind is not None and envelope["kind"] != expected_kind:
        return False, f"unexpected kind: {envelope['kind']} != {expected_kind}"

    return True, ""


def verify_envelope_signature(
    envelope: dict,
    sender_ed25519_pub: str,
) -> bool:
    """Verify ONLY the Ed25519 signature, assuming the caller has already checked
    freshness and structure. Returns True/False (never raises)."""
    sig = envelope.pop("sig", None)
    if sig is None:
        # Restore and fail.
        envelope["sig"] = sig
        return False
    try:
        payload = _canonical_json(envelope)
        result = verify_signature(sender_ed25519_pub, payload, sig)
    finally:
        # Always restore the envelope dict.
        envelope["sig"] = sig
    return result


# ---------------------------------------------------------------------------
# Peer tokens
# ---------------------------------------------------------------------------

_PEER_TOKEN_BYTES = 32


def mint_peer_token(sub: str) -> tuple[str, str]:
    """Mint a new peer token for a contact.

    Returns ``(plaintext_token, token_hash)``.  The plaintext is given to the
    remote instance; the hash is stored in ``peer_links.inbound_token_hash``.

    ``sub`` is the token subject, e.g. ``"contact:hogne"``.

    Uses the same plain SHA-256 as ``ContactsStore._hash_token`` so that
    minting and verification are consistent.
    """
    import secrets

    raw = secrets.token_hex(_PEER_TOKEN_BYTES)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, token_hash


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _canonical_json(obj: dict) -> bytes:
    """Canonical JSON: sorted keys, compact, UTF-8 bytes (no trailing newline)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
