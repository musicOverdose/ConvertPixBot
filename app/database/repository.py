"""Database repository for channels, stats, and jobs."""

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Optional, List
import aiosqlite

from app.database.connection import Database
from app.database.models import (
    AdminAuditLog,
    BannedUser,
    BotStatistic,
    BroadcastRecord,
    JobRecord,
    RequiredChannel,
    WhitelistedUser,
)

logger = logging.getLogger(__name__)


class DatabaseRepository:
    """Async repository providing high-level CRUD operations for the bot."""

    def __init__(self, db: Database):
        self.db = db

    async def _get_conn(self) -> aiosqlite.Connection:
        return await self.db.connect()

    # --- Required Channels CRUD ---

    async def add_channel(
        self,
        channel_id: str,
        username: Optional[str] = None,
        title: Optional[str] = None,
        invite_link: Optional[str] = None,
    ) -> bool:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO required_channels (channel_id, username, title, invite_link, is_enabled, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    username = excluded.username,
                    title = excluded.title,
                    invite_link = excluded.invite_link,
                    is_enabled = 1;
                """,
                (channel_id, username, title, invite_link, now),
            )
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding channel {channel_id}: {e}")
            return False

    async def remove_channel(self, channel_id: str) -> bool:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                "DELETE FROM required_channels WHERE channel_id = ? OR username = ?;",
                (channel_id, channel_id.lstrip("@")),
            )
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error removing channel {channel_id}: {e}")
            return False

    async def set_channel_enabled(self, channel_id: str, is_enabled: bool) -> bool:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                "UPDATE required_channels SET is_enabled = ? WHERE channel_id = ? OR username = ?;",
                (1 if is_enabled else 0, channel_id, channel_id.lstrip("@")),
            )
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error setting channel {channel_id} status: {e}")
            return False

    async def list_channels(self, enabled_only: bool = False) -> List[RequiredChannel]:
        conn = await self._get_conn()
        query = "SELECT id, channel_id, username, title, invite_link, is_enabled, created_at FROM required_channels"
        if enabled_only:
            query += " WHERE is_enabled = 1"
        query += " ORDER BY id ASC;"

        async with conn.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [
                RequiredChannel(
                    id=row["id"],
                    channel_id=row["channel_id"],
                    username=row["username"],
                    title=row["title"],
                    invite_link=row["invite_link"],
                    is_enabled=bool(row["is_enabled"]),
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    # --- Statistics ---

    async def increment_stat(self, key: str, amount: int = 1) -> None:
        conn = await self._get_conn()
        try:
            await conn.execute(
                """
                INSERT INTO bot_stats (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = value + excluded.value;
                """,
                (key, amount),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error incrementing stat {key}: {e}")

    async def record_user_activity(self, user_id: int) -> None:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO active_users (user_id, first_seen, last_seen) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET last_seen = excluded.last_seen;
                """,
                (user_id, now, now),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error recording user {user_id}: {e}")

    async def get_stats(self) -> BotStatistic:
        conn = await self._get_conn()
        stats_map = {}
        async with conn.execute("SELECT key, value FROM bot_stats;") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                stats_map[row["key"]] = row["value"]

        # Count active users
        user_count = 0
        async with conn.execute("SELECT COUNT(*) as cnt FROM active_users;") as cursor:
            row = await cursor.fetchone()
            if row:
                user_count = row["cnt"]

        return BotStatistic(
            files_received=stats_map.get("files_received", 0),
            files_processed=stats_map.get("files_processed", 0),
            files_failed=stats_map.get("files_failed", 0),
            cuts_performed=stats_map.get("cuts_performed", 0),
            covers_updated=stats_map.get("covers_updated", 0),
            lyrics_updated=stats_map.get("lyrics_updated", 0),
            unique_users=user_count,
            total_processed_bytes=stats_map.get("total_processed_bytes", 0),
        )

    # --- Job Tracking ---

    async def register_job(self, uuid_str: str, user_id: int, chat_id: int, filename: str, file_size: int) -> None:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO active_jobs (uuid, user_id, chat_id, filename, file_size, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?);
                """,
                (uuid_str, user_id, chat_id, filename, file_size, now, now),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error registering job {uuid_str}: {e}")

    async def update_job_status(self, uuid_str: str, status: str) -> None:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                "UPDATE active_jobs SET status = ?, updated_at = ? WHERE uuid = ?;",
                (status, now, uuid_str),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error updating job {uuid_str}: {e}")

    async def delete_job_record(self, uuid_str: str) -> None:
        conn = await self._get_conn()
        try:
            await conn.execute("DELETE FROM active_jobs WHERE uuid = ?;", (uuid_str,))
            await conn.commit()
        except Exception as e:
            logger.error(f"Error deleting job {uuid_str}: {e}")

    # --- Whitelist Operations ---

    async def add_to_whitelist(
        self,
        user_id: int,
        username: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO whitelist_users (user_id, username, reason, added_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    reason = excluded.reason;
                """,
                (user_id, username, reason, now),
            )
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding user {user_id} to whitelist: {e}")
            return False

    async def remove_from_whitelist(self, user_id: int) -> bool:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                "DELETE FROM whitelist_users WHERE user_id = ?;", (user_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error removing user {user_id} from whitelist: {e}")
            return False

    async def is_whitelisted(self, user_id: int) -> bool:
        conn = await self._get_conn()
        try:
            async with conn.execute(
                "SELECT 1 FROM whitelist_users WHERE user_id = ?;", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None
        except Exception as e:
            logger.error(f"Error checking whitelist for user {user_id}: {e}")
            return False

    async def list_whitelist(self) -> List[WhitelistedUser]:
        conn = await self._get_conn()
        try:
            async with conn.execute(
                "SELECT user_id, username, reason, added_at FROM whitelist_users ORDER BY added_at DESC;"
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    WhitelistedUser(
                        user_id=row["user_id"],
                        username=row["username"],
                        reason=row["reason"],
                        added_at=row["added_at"],
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error listing whitelist: {e}")
            return []

    # --- Ban List Operations ---

    async def ban_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO banned_users (user_id, username, reason, banned_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    reason = excluded.reason;
                """,
                (user_id, username, reason, now),
            )
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error banning user {user_id}: {e}")
            return False

    async def unban_user(self, user_id: int) -> bool:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                "DELETE FROM banned_users WHERE user_id = ?;", (user_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error unbanning user {user_id}: {e}")
            return False

    async def is_banned(self, user_id: int) -> bool:
        conn = await self._get_conn()
        try:
            async with conn.execute(
                "SELECT 1 FROM banned_users WHERE user_id = ?;", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None
        except Exception as e:
            logger.error(f"Error checking ban for user {user_id}: {e}")
            return False

    async def list_banned(self) -> List[BannedUser]:
        conn = await self._get_conn()
        try:
            async with conn.execute(
                "SELECT user_id, username, reason, banned_at FROM banned_users ORDER BY banned_at DESC;"
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    BannedUser(
                        user_id=row["user_id"],
                        username=row["username"],
                        reason=row["reason"],
                        banned_at=row["banned_at"],
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error listing banned users: {e}")
            return []

    # --- Active User IDs for Broadcast ---

    async def get_all_active_user_ids(self) -> List[int]:
        conn = await self._get_conn()
        try:
            async with conn.execute("SELECT user_id FROM active_users ORDER BY user_id ASC;") as cursor:
                rows = await cursor.fetchall()
                return [row["user_id"] for row in rows]
        except Exception as e:
            logger.error(f"Error fetching active user ids: {e}")
            return []

    # --- System Settings & Maintenance Mode ---

    async def get_system_setting(self, key: str, default: str = "") -> str:
        conn = await self._get_conn()
        try:
            async with conn.execute(
                "SELECT value FROM system_settings WHERE key = ?;", (key,)
            ) as cursor:
                row = await cursor.fetchone()
                return str(row["value"]) if row else default
        except Exception as e:
            logger.error(f"Error getting system setting {key}: {e}")
            return default

    async def set_system_setting(self, key: str, value: str) -> None:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at;
                """,
                (key, value, now),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error setting system setting {key}: {e}")

    async def delete_system_setting(self, key: str) -> bool:
        """Deletes a system setting row from the database (reverting to default)."""
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                "DELETE FROM system_settings WHERE key = ?;", (key,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting system setting {key}: {e}")
            return False

    async def is_maintenance_mode(self) -> bool:
        val = await self.get_system_setting("maintenance_mode", "false")
        return val.strip().lower() in ("true", "1", "yes")

    async def set_maintenance_mode(self, enabled: bool) -> None:
        await self.set_system_setting("maintenance_mode", "true" if enabled else "false")

    # --- Admin Audit Logging ---

    async def log_audit_action(
        self,
        admin_id: int,
        action: str,
        target: Optional[str] = None,
        details: Optional[str] = None,
    ) -> bool:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO admin_audit_logs (admin_id, action, target, details, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (admin_id, action, target, details, now),
            )
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error logging audit action {action}: {e}")
            return False

    async def get_audit_logs(self, limit: int = 10, offset: int = 0) -> tuple[List[AdminAuditLog], int]:
        conn = await self._get_conn()
        try:
            total_count = 0
            async with conn.execute("SELECT COUNT(*) as cnt FROM admin_audit_logs;") as count_cur:
                row = await count_cur.fetchone()
                if row:
                    total_count = row["cnt"]

            query = (
                "SELECT id, admin_id, action, target, details, created_at "
                "FROM admin_audit_logs ORDER BY id DESC LIMIT ? OFFSET ?;"
            )
            async with conn.execute(query, (limit, offset)) as cursor:
                rows = await cursor.fetchall()
                logs = [
                    AdminAuditLog(
                        id=r["id"],
                        admin_id=r["admin_id"],
                        action=r["action"],
                        target=r["target"],
                        details=r["details"],
                        created_at=r["created_at"],
                    )
                    for r in rows
                ]
                return logs, total_count
        except Exception as e:
            logger.error(f"Error retrieving audit logs: {e}")
            return [], 0

    # --- Broadcast History ---

    async def create_broadcast_record(
        self,
        admin_id: int,
        source_chat_id: int,
        source_message_id: int,
        text_preview: Optional[str],
        total_targets: int,
    ) -> int:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        # Strictly cap preview length to 120 characters and avoid saving private payloads
        safe_preview = (text_preview[:120].strip() + "...") if text_preview and len(text_preview) > 120 else text_preview
        try:
            cursor = await conn.execute(
                """
                INSERT INTO broadcast_history (
                    admin_id, source_chat_id, source_message_id, text_preview,
                    total_targets, delivered_count, blocked_count, failed_count,
                    status, created_at
                )
                VALUES (?, ?, ?, ?, ?, 0, 0, 0, 'running', ?);
                """,
                (admin_id, source_chat_id, source_message_id, safe_preview, total_targets, now),
            )
            await conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating broadcast record: {e}")
            return 0

    async def update_broadcast_progress(
        self,
        broadcast_id: int,
        delivered: int,
        blocked: int,
        failed: int,
        status: str = "running",
    ) -> None:
        conn = await self._get_conn()
        try:
            await conn.execute(
                """
                UPDATE broadcast_history
                SET delivered_count = ?, blocked_count = ?, failed_count = ?, status = ?
                WHERE id = ?;
                """,
                (delivered, blocked, failed, status, broadcast_id),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error updating broadcast progress {broadcast_id}: {e}")

    async def complete_broadcast_record(
        self,
        broadcast_id: int,
        delivered: int,
        blocked: int,
        failed: int,
        status: str = "completed",
    ) -> None:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            await conn.execute(
                """
                UPDATE broadcast_history
                SET delivered_count = ?, blocked_count = ?, failed_count = ?, status = ?, completed_at = ?
                WHERE id = ?;
                """,
                (delivered, blocked, failed, status, now, broadcast_id),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error completing broadcast record {broadcast_id}: {e}")

    async def get_broadcast_record(self, broadcast_id: int) -> Optional[BroadcastRecord]:
        conn = await self._get_conn()
        try:
            async with conn.execute(
                "SELECT * FROM broadcast_history WHERE id = ?;", (broadcast_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return BroadcastRecord(
                    id=row["id"],
                    admin_id=row["admin_id"],
                    source_chat_id=row["source_chat_id"],
                    source_message_id=row["source_message_id"],
                    text_preview=row["text_preview"],
                    total_targets=row["total_targets"],
                    delivered_count=row["delivered_count"],
                    blocked_count=row["blocked_count"],
                    failed_count=row["failed_count"],
                    status=row["status"],
                    created_at=row["created_at"],
                    completed_at=row["completed_at"],
                )
        except Exception as e:
            logger.error(f"Error fetching broadcast record {broadcast_id}: {e}")
            return None

    # --- Job State Reconciliation ---

    async def reconcile_interrupted_jobs(self) -> int:
        """
        Marks active or queued jobs from previous ungraceful exits as 'interrupted'.
        """
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = await conn.execute(
                """
                UPDATE active_jobs
                SET status = 'interrupted', updated_at = ?
                WHERE status IN ('active', 'processing', 'queued');
                """,
                (now,),
            )
            await conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(f"Error reconciling interrupted jobs: {e}")
            return 0

    # --- SQLite Database Backup & Pruning ---

    async def backup_database(self, backup_dir: Path, retention_days: int = 7) -> Path:
        """
        Creates a live backup of the SQLite database and prunes backups older than retention_days.
        """
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"bot_backup_{timestamp}.db"

        # Perform live online backup
        await self.db.backup(backup_file)

        # Retention pruning
        try:
            cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
            existing_backups = sorted(backup_dir.glob("bot_backup_*.db"))
            # Keep at least the 2 newest backups regardless of age
            if len(existing_backups) > 2:
                for b_file in existing_backups[:-2]:
                    if b_file.stat().st_mtime < cutoff:
                        b_file.unlink(missing_ok=True)
                        logger.info(f"Pruned old database backup: {b_file}")
        except Exception as e:
            logger.warning(f"Error during backup retention cleanup: {e}")

        return backup_file


