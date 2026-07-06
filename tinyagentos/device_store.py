from __future__ import annotations

import secrets
import uuid

from tinyagentos.base_store import BaseStore

DEVICE_TOKEN_PREFIX = "taosdev_"

# Columns returned to internal callers (includes the secret scoped_token).
_FULL_COLS = (
    "device_id, user_id, platform, push_token, scoped_token, "
    "display_name, registered_at, last_seen, revoked"
)
# Columns safe to return to the owning user (no scoped_token).
_SAFE_COLS = (
    "device_id, user_id, platform, push_token, "
    "display_name, registered_at, last_seen, revoked"
)


def _row(cols: str, values) -> dict:
    return dict(zip(cols.split(", "), values))


class DeviceStore(BaseStore):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS devices (
        device_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        push_token TEXT NOT NULL DEFAULT '',
        scoped_token TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL DEFAULT '',
        registered_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        last_seen INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        revoked INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
    CREATE INDEX IF NOT EXISTS idx_devices_token ON devices(scoped_token);
    """

    async def register(
        self, *, user_id: str, platform: str, push_token: str = "", display_name: str = ""
    ) -> dict:
        assert self._db is not None
        device_id = uuid.uuid4().hex
        scoped_token = DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
        await self._db.execute(
            "INSERT INTO devices (device_id, user_id, platform, push_token, "
            "scoped_token, display_name) VALUES (?, ?, ?, ?, ?, ?)",
            (device_id, user_id, platform, push_token, scoped_token, display_name),
        )
        await self._db.commit()
        got = await self.get(device_id)
        assert got is not None
        return got

    async def get(self, device_id: str) -> dict | None:
        assert self._db is not None
        cur = await self._db.execute(
            f"SELECT {_FULL_COLS} FROM devices WHERE device_id = ?", (device_id,)
        )
        row = await cur.fetchone()
        return _row(_FULL_COLS, row) if row else None

    async def get_by_token(self, scoped_token: str) -> dict | None:
        assert self._db is not None
        cur = await self._db.execute(
            f"SELECT {_FULL_COLS} FROM devices WHERE scoped_token = ? AND revoked = 0",
            (scoped_token,),
        )
        row = await cur.fetchone()
        return _row(_FULL_COLS, row) if row else None

    async def list_for_user(self, user_id: str) -> list[dict]:
        assert self._db is not None
        cur = await self._db.execute(
            f"SELECT {_SAFE_COLS} FROM devices WHERE user_id = ? AND revoked = 0 "
            "ORDER BY registered_at DESC, device_id DESC",
            (user_id,),
        )
        return [_row(_SAFE_COLS, r) for r in await cur.fetchall()]

    async def update_push_token(self, device_id: str, push_token: str) -> dict | None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE devices SET push_token = ? WHERE device_id = ?",
            (push_token, device_id),
        )
        await self._db.commit()
        return await self.get(device_id)

    async def touch(self, device_id: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE devices SET last_seen = strftime('%s','now') WHERE device_id = ?",
            (device_id,),
        )
        await self._db.commit()

    async def revoke(self, device_id: str) -> bool:
        assert self._db is not None
        cur = await self._db.execute(
            "UPDATE devices SET revoked = 1 WHERE device_id = ? AND revoked = 0",
            (device_id,),
        )
        await self._db.commit()
        return cur.rowcount > 0
