"""SQLite database connection and schema initialization."""

import asyncio
import logging
import os
from pathlib import Path
import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS required_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT UNIQUE NOT NULL,
    username TEXT,
    title TEXT,
    invite_link TEXT,
    is_enabled BOOLEAN DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_stats (
    key TEXT PRIMARY KEY,
    value INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS active_users (
    user_id INTEGER PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS active_jobs (
    uuid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS whitelist_users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    reason TEXT,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    reason TEXT,
    banned_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcast_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    source_chat_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    text_preview TEXT,
    total_targets INTEGER DEFAULT 0,
    delivered_count INTEGER DEFAULT 0,
    blocked_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""


class Database:
    """Manages async SQLite connections and migrations."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        if self._connection is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            if not os.access(self.db_path.parent, os.W_OK):
                uid = os.getuid() if hasattr(os, "getuid") else "N/A"
                gid = os.getgid() if hasattr(os, "getgid") else "N/A"
                logger.error(
                    f"Database directory '{self.db_path.parent}' is not writable! "
                    f"Current UID={uid}, GID={gid}. "
                    f"If running in Docker/Portainer, ensure host volume has permissions for UID 10001: "
                    f"'sudo chown -R 10001:10001 <path_to_data>'"
                )
            self._connection = await aiosqlite.connect(str(self.db_path))
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA journal_mode=WAL;")
            await self._connection.execute("PRAGMA synchronous=NORMAL;")
            await self.init_schema()
        return self._connection

    async def init_schema(self) -> None:
        if self._connection:
            await self._connection.executescript(SCHEMA_SQL)
            await self._connection.commit()
            logger.info("Database schema initialized successfully.")

    async def backup(self, dest_path: Path) -> None:
        """
        Creates a consistent live backup of the SQLite database.
        Prefers Python's sqlite3 online backup API, with VACUUM INTO fallback.
        """
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            dest_path.unlink()

        def _do_online_backup():
            import sqlite3
            src_conn = sqlite3.connect(str(self.db_path))
            try:
                dest_conn = sqlite3.connect(str(dest_path))
                try:
                    src_conn.backup(dest_conn)
                finally:
                    dest_conn.close()
            finally:
                src_conn.close()

        try:
            await asyncio.to_thread(_do_online_backup)
            logger.info(f"SQLite online backup successful: {dest_path}")
        except Exception as e:
            logger.warning(f"SQLite online backup API failed ({e}), attempting VACUUM INTO fallback...")
            conn = await self.connect()
            dest_escaped = str(dest_path).replace("'", "''")
            await conn.execute(f"VACUUM INTO '{dest_escaped}';")
            logger.info(f"VACUUM INTO backup successful: {dest_path}")

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None

