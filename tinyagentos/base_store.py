from __future__ import annotations
from pathlib import Path
import aiosqlite

from tinyagentos.db_migrations import apply_wal_pragmas_async, run_migrations_async


class BaseStore:
    """Base class for all SQLite-backed stores.

    Subclasses set ``SCHEMA`` (applied once on first open) and may set
    ``MIGRATIONS`` to a list of ``(version, sql_or_callable)`` pairs that
    will be tracked and applied in order by the migration runner.

    WARNING: init order is SCHEMA -> MIGRATIONS -> _post_init.  Never
    reference a column inside SCHEMA that is introduced by a migration —
    the SCHEMA executescript runs first and will crash on any existing
    database that lacks the column.  This applies to CREATE INDEX too:
    any CREATE INDEX in SCHEMA that references a column added by _post_init
    will brick boot on existing databases — the column won't exist yet when
    the index is created.  The fix is to move such indexes into _post_init
    after the ALTER TABLE that introduces the column.

    The migration runner uses baseline-at-latest semantics: pre-existing
    databases are stamped at the latest version without executing any SQL,
    so retrofit migrations are silently skipped.  Use a guarded _post_init
    coroutine (PRAGMA table_info check + ALTER TABLE only when absent) for
    columns added after initial release.  See db_migrations.py module
    docstring and tests/test_store_upgrades.py for the regression gate.
    """
    SCHEMA: str = ""
    # List of (version: int, sql_or_callable) pairs. See db_migrations.py.
    MIGRATIONS: list = []

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        await apply_wal_pragmas_async(self._db)
        if self.SCHEMA:
            await self._db.executescript(self.SCHEMA)
            await self._db.commit()
        if self.MIGRATIONS:
            await run_migrations_async(self._db, self.MIGRATIONS)
        await self._post_init()

    async def _post_init(self) -> None:
        """Override in subclasses for seeding data after schema creation."""
        pass

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
