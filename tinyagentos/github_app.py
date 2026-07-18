"""GitHub App authentication helpers.

Generates JWTs for app-to-GitHub API communication, mints short-lived
installation tokens, and lists installations/repos. Uses ``cryptography``
for RS256 signing (already a project dependency).

API reference: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app
"""
from __future__ import annotations

import base64
import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

# Simple in-memory token cache with TTL (avoids minting a new JWT + token
# on every API call when the same installation is used repeatedly).
_token_cache: dict[str, tuple[str, float]] = {}  # key -> (token, expiry)
_CACHE_TTL = 300  # 5 minutes (token lifetime is 1 hour, so this is conservative)


def _cache_key(app_id: str, installation_id: int) -> str:
    """Return a cache key for an app_id + installation_id pair."""
    return f"{app_id}:{installation_id}"


def _cached_token(key: str) -> str | None:
    """Return a cached token if valid, or None."""
    entry = _token_cache.get(key)
    if entry:
        token, expiry = entry
        if time.time() < expiry:
            return token
        del _token_cache[key]
    return None


def _cache_token(key: str, token: str) -> None:
    """Store a token in the cache with the default TTL."""
    _token_cache[key] = (token, time.time() + _CACHE_TTL)

# ---------------------------------------------------------------------------
# GitHub App API endpoints
# ---------------------------------------------------------------------------

_GH_API = "https://api.github.com"
_GH_APP_INSTALLATIONS = f"{_GH_API}/app/installations"
_INSTALL_TOKEN_URL = f"{_GH_API}/app/installations/{{installation_id}}/access_tokens"
_APP_SLUG_URL = f"{_GH_API}/app"


def _b64url(data: bytes) -> str:
    """URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_jwt(app_id: str, private_key: str) -> str:
    """Generate a GitHub App JWT (RS256) for app-to-API authentication.

    The JWT is valid for 10 minutes (GitHub's maximum). It identifies the
    app itself (not a specific installation).
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iat": now - 60,         # 60s clock drift tolerance
        "exp": now + 600,        # max 10 min per GitHub spec
        "iss": str(app_id),
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    key = serialization.load_pem_private_key(private_key.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("GitHub App private key must be an RSA private key")
    signature = key.sign(
        signing_input.encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return signing_input + "." + _b64url(signature)


def _auth_headers(jwt: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _get_app_slug(
    app_id: str,
    private_key: str,
    http_client: httpx.AsyncClient,
) -> str | None:
    """Return the GitHub App's slug name, or None on failure."""
    jwt = generate_jwt(app_id, private_key)
    try:
        resp = await http_client.get(
            _APP_SLUG_URL,
            headers=_auth_headers(jwt),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("slug")
    except Exception as exc:
        logger.warning("Failed to get app slug: %s", exc)
        return None


async def get_installation_token(
    app_id: str,
    private_key: str,
    installation_id: int,
    http_client: httpx.AsyncClient,
) -> str | None:
    """Mint a short-lived installation access token.

    Returns the token string or None on failure. The token is scoped to the
    repositories the installation has access to and expires after 1 hour.
    Results are cached for 5 minutes to avoid minting a new JWT + token
    on every API call.
    """
    key = _cache_key(app_id, installation_id)
    cached = _cached_token(key)
    if cached:
        return cached

    jwt = generate_jwt(app_id, private_key)
    url = _INSTALL_TOKEN_URL.format(installation_id=installation_id)
    try:
        resp = await http_client.post(
            url,
            headers=_auth_headers(jwt),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token")
        if token:
            _cache_token(key, token)
        return token
    except Exception as exc:
        logger.exception(
            "Failed to get installation token for installation %s: %s",
            installation_id,
            exc,
        )
        return None


async def list_installations(
    app_id: str,
    private_key: str,
    http_client: httpx.AsyncClient,
) -> list[dict]:
    """List all installations of the GitHub App (follows pagination).

    Returns a list of installation dicts, each containing:
      - id (int): installation ID
      - account (dict): login, avatar_url, type (User/Organization)
      - repository_selection: "selected" or "all"
      - created_at, updated_at
    """
    jwt = generate_jwt(app_id, private_key)
    all_installations: list[dict] = []
    page = 1
    while True:
        try:
            resp = await http_client.get(
                _GH_APP_INSTALLATIONS,
                headers=_auth_headers(jwt),
                params={"per_page": 100, "page": page},
                timeout=15,
            )
            resp.raise_for_status()
            installations = resp.json()
            if not installations:
                break
            all_installations.extend(installations)
            if len(installations) < 100:
                break
            page += 1
        except Exception as exc:
            logger.exception("Failed to list installations: %s", exc)
            break
    return all_installations


async def list_installation_repos(
    installation_token: str,
    http_client: httpx.AsyncClient,
) -> list[dict]:
    """List repositories accessible to an installation.

    Returns a list of repo dicts from the GitHub API.
    """
    headers = {
        "Authorization": f"Bearer {installation_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    all_repos: list[dict] = []
    page = 1
    while True:
        try:
            resp = await http_client.get(
                f"{_GH_API}/installation/repositories",
                headers=headers,
                params={"per_page": 100, "page": page},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            repos = data.get("repositories", [])
            if not repos:
                break
            all_repos.extend(repos)
            if len(repos) < 100:
                break
            page += 1
        except Exception as exc:
            logger.exception("Failed to list installation repos: %s", exc)
            break
    return all_repos


async def delete_installation(
    app_id: str,
    private_key: str,
    installation_id: int,
    http_client: httpx.AsyncClient,
) -> bool:
    """Delete (uninstall) a GitHub App installation."""
    jwt = generate_jwt(app_id, private_key)
    url = f"{_GH_APP_INSTALLATIONS}/{installation_id}"
    try:
        resp = await http_client.delete(
            url,
            headers=_auth_headers(jwt),
            timeout=15,
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.exception(
            "Failed to delete installation %s: %s", installation_id, exc
        )
        return False
