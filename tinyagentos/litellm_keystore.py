"""In-house per-agent LiteLLM key store.

The alternative to LiteLLM's Postgres/prisma virtual-key table. The
controller mints a random per-agent token here with its allowed model
list; the LiteLLM ``custom_auth`` hook (``tinyagentos.litellm_auth``)
reads the same store to authorize incoming requests. Both processes open
the same SQLite file, so this works with NO ``DATABASE_URL`` and no prisma
(the whole point: virtual keys on ARM / no-Postgres installs).

Scope intentionally tiny: mint, lookup, re-scope, delete. Spend/budget
tracking stays in taOS's existing trace/observability layer, not here.

The same file also holds the in-process LLM gateway's scoped keys
(``gateway_keys``, see ``tinyagentos.llm_gateway.auth``). Those are stored as
a SHA-256 hash only -- the plaintext is returned once at mint and never
written -- and carry a principal (agent id or ``node:<id>``), an optional
expiry and a revoked timestamp. The legacy ``agent_keys`` rows keep their
plaintext token (the LiteLLM hook still needs it) and gain a ``token_hash``
column so the gateway can find them by hash and compare in constant time.

``agent_keys`` rows also carry a ``kind``: ``agent`` (the default, and what
every pre-existing row is) or ``app``. An app principal (#613) is bound to
``app:<app id>`` and is minted when a model-consuming app is installed, so an
installed app gets its own model-scoped credential instead of the shared
master key. Both surfaces honour it: the LiteLLM hook reads the plaintext row,
the gateway reads the hashed row, and both enforce the same allowlist.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from tinyagentos.db_migrations import apply_wal_pragmas

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_keys (
    token           TEXT PRIMARY KEY,
    agent           TEXT NOT NULL,
    allowed_models  TEXT NOT NULL,
    created_ts      REAL NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'agent'
);
CREATE INDEX IF NOT EXISTS idx_agent_keys_agent ON agent_keys(agent);
CREATE TABLE IF NOT EXISTS gateway_keys (
    key_id          TEXT PRIMARY KEY,
    key_hash        TEXT NOT NULL UNIQUE,
    bound_to        TEXT NOT NULL,
    kind            TEXT NOT NULL,
    allowed_models  TEXT NOT NULL,
    created_ts      REAL NOT NULL,
    expires_ts      REAL,
    revoked_ts      REAL
);
CREATE INDEX IF NOT EXISTS idx_gateway_keys_bound ON gateway_keys(bound_to);
"""


def token_hash(token: str) -> str:
    """SHA-256 hex of a bearer token: what is stored and looked up.

    A fast hash is correct here (no KDF): every token is 256 bits of
    ``secrets`` randomness, so there is nothing to brute-force.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

# taos-prefixed so the key is recognisable in logs and never collides with
# LiteLLM's own sk- keys.
_TOKEN_PREFIX = "sk-taos-"

# Principal kinds for an ``agent_keys`` row (#613). ``agent`` is the default,
# and what every row written before app principals existed is. ``app`` binds an
# installed app's key to ``app:<app id>``, mirroring the gateway's ``node:<id>``
# convention.
KIND_AGENT = "agent"
KIND_APP = "app"
PRINCIPAL_KINDS = frozenset({KIND_AGENT, KIND_APP})
APP_PRINCIPAL_PREFIX = "app:"


def app_principal(app_id: str) -> str:
    """The principal id an installed app's key is bound to (#613)."""
    if not isinstance(app_id, str) or not app_id:
        raise ValueError("app_id must be a non-empty string")
    if app_id.startswith(APP_PRINCIPAL_PREFIX):
        return app_id
    return APP_PRINCIPAL_PREFIX + app_id


def _validate_principal(principal: str, kind: str) -> None:
    """Reject a principal whose name contradicts its kind.

    Same shape as the gateway's node rule: an app principal is always
    ``app:<id>``, an agent principal never is. Without this a caller could mint
    an ``app``-kind key for a bare agent name and get app semantics (no agent
    budget enforcement, app wording in the refusals) for an agent.
    """
    if not isinstance(principal, str) or not principal:
        raise ValueError("principal must be a non-empty string")
    if kind not in PRINCIPAL_KINDS:
        raise ValueError(f"kind must be one of {sorted(PRINCIPAL_KINDS)}")
    is_app = principal.startswith(APP_PRINCIPAL_PREFIX)
    if (kind == KIND_APP) != is_app:
        raise ValueError(
            "app principals are named 'app:<id>'; agent principals never are"
        )
    if is_app and len(principal) == len(APP_PRINCIPAL_PREFIX):
        raise ValueError("app principal has an empty id")


class LiteLLMKeyStore:
    """SQLite-backed per-agent key store, safe for cross-process read/write.

    The controller writes (mint/rescope/delete); the LiteLLM subprocess's
    auth hook only reads. WAL mode keeps a concurrent reader from blocking
    on a writer.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        apply_wal_pragmas(conn)
        return conn

    def _init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate_agent_key_hashes(conn)
            self._migrate_agent_key_kinds(conn)

    @staticmethod
    def _migrate_agent_key_kinds(conn: sqlite3.Connection) -> None:
        """Add ``agent_keys.kind``, defaulting existing rows to 'agent'.

        Idempotent and race-tolerant for the same reason as the hash migration:
        the controller and the LiteLLM subprocess both open this file, and an
        older binary may still INSERT without the column.
        """
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(agent_keys)")}
        if "kind" not in cols:
            try:
                conn.execute(
                    "ALTER TABLE agent_keys ADD COLUMN kind TEXT NOT NULL DEFAULT 'agent'"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        # A row written by an old process (or before the ALTER) can carry NULL.
        conn.execute("UPDATE agent_keys SET kind = 'agent' WHERE kind IS NULL OR kind = ''")

    @staticmethod
    def _migrate_agent_key_hashes(conn: sqlite3.Connection) -> None:
        """Add and backfill ``agent_keys.token_hash`` (idempotent).

        Both the controller and the LiteLLM subprocess open this file, so the
        ALTER can race; a duplicate-column error just means the other process
        won.
        """
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(agent_keys)")}
        if "token_hash" not in cols:
            try:
                conn.execute("ALTER TABLE agent_keys ADD COLUMN token_hash TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_keys_hash ON agent_keys(token_hash)"
        )
        rows = conn.execute(
            "SELECT token FROM agent_keys WHERE token_hash IS NULL"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE agent_keys SET token_hash = ? WHERE token = ?",
                (token_hash(row["token"]), row["token"]),
            )

    def mint(self, principal: str, allowed_models: list[str] | None,
             kind: str = KIND_AGENT) -> str:
        """Create a fresh token for a principal scoped to allowed_models.

        An empty/None allowlist is stored as ``[]`` (deny-all rather than a
        bogus "default" alias) so the hook can enforce it explicitly.

        ``kind`` is ``agent`` (``principal`` = agent id) or ``app``
        (``principal`` = ``app:<app id>``; prefer :func:`app_principal`).
        """
        _validate_principal(principal, kind)
        token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
        models_json = json.dumps(list(allowed_models or []))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agent_keys "
                "(token, agent, allowed_models, created_ts, token_hash, kind) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (token, principal, models_json, time.time(), token_hash(token), kind),
            )
        return token

    def lookup(self, token: str) -> dict | None:
        """Return ``{agent, kind, allowed_models}`` for a token, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT agent, kind, allowed_models FROM agent_keys WHERE token = ?",
                (token,),
            ).fetchone()
        if row is None:
            return None
        return {
            "agent": row["agent"],
            "kind": row["kind"] or KIND_AGENT,
            "allowed_models": _models(row["allowed_models"]),
        }

    def keys_for_principal(self, principal: str) -> list[dict]:
        """Every key minted for ``principal``, oldest first.

        Each entry is ``{token, kind, allowed_models, created_ts}``. Used by the
        per-app access surface (#613) to read and re-scope an app's key without
        persisting the token anywhere else.
        """
        if not isinstance(principal, str) or not principal:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT token, kind, allowed_models, created_ts FROM agent_keys "
                "WHERE agent = ? ORDER BY created_ts",
                (principal,),
            ).fetchall()
        return [
            {
                "token": r["token"],
                "kind": r["kind"] or KIND_AGENT,
                "allowed_models": _models(r["allowed_models"]),
                "created_ts": r["created_ts"],
            }
            for r in rows
        ]

    def set_models(self, token: str, allowed_models: list[str]) -> bool:
        """Re-scope a token's allowed models in place. Returns True if it existed."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE agent_keys SET allowed_models = ? WHERE token = ?",
                (json.dumps(list(allowed_models or [])), token),
            )
            return cur.rowcount > 0

    def delete(self, token: str) -> bool:
        """Remove a token. Returns True if it existed."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM agent_keys WHERE token = ?", (token,))
            return cur.rowcount > 0

    def delete_agent(self, agent: str) -> int:
        """Remove all tokens for an agent (e.g. on undeploy). Returns count."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM agent_keys WHERE agent = ?", (agent,))
            return cur.rowcount

    # -- hashed lookups + gateway keys (tinyagentos.llm_gateway.auth) -------

    def agent_key_by_hash(self, key_hash: str) -> dict | None:
        """Legacy key by ``token_hash``: ``{agent, kind, allowed_models,
        token_hash}`` or None. The caller compares ``token_hash`` itself."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT agent, kind, allowed_models, token_hash FROM agent_keys "
                "WHERE token_hash = ?",
                (key_hash,),
            ).fetchone()
        if row is None:
            return None
        return {
            "agent": row["agent"],
            "kind": row["kind"] or KIND_AGENT,
            "allowed_models": _models(row["allowed_models"]),
            "token_hash": row["token_hash"],
        }

    def insert_gateway_key(
        self,
        *,
        key_id: str,
        key_hash: str,
        bound_to: str,
        kind: str,
        allowed_models: list[str],
        expires_ts: float | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO gateway_keys (key_id, key_hash, bound_to, kind, "
                "allowed_models, created_ts, expires_ts, revoked_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (key_id, key_hash, bound_to, kind, json.dumps(list(allowed_models)),
                 time.time(), expires_ts),
            )

    def gateway_key_by_hash(self, key_hash: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT key_id, key_hash, bound_to, kind, allowed_models, "
                "expires_ts, revoked_ts FROM gateway_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
        if row is None:
            return None
        rec = {k: row[k] for k in row.keys()}
        rec["allowed_models"] = _models(row["allowed_models"])
        return rec

    def revoke_bound(self, bound_to: str) -> int:
        """Kill every key bound to a principal: gateway keys are marked
        revoked (kept for audit), legacy agent_keys rows for the same name are
        deleted. Returns how many live keys died."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE gateway_keys SET revoked_ts = ? "
                "WHERE bound_to = ? AND revoked_ts IS NULL",
                (time.time(), bound_to),
            )
            n = cur.rowcount
            cur = conn.execute("DELETE FROM agent_keys WHERE agent = ?", (bound_to,))
            return n + cur.rowcount


def _models(raw) -> list[str]:
    try:
        models = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, str)]


def default_keystore_path(data_dir: str | Path) -> Path:
    """Canonical keystore path for a controller data dir."""
    return Path(data_dir) / ".litellm_keys.db"
