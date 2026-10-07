"""Database models and data transfer objects."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class RequiredChannel:
    id: Optional[int] = None
    channel_id: str = ""  # @username or -100123456789
    username: Optional[str] = None
    title: Optional[str] = None
    invite_link: Optional[str] = None
    is_enabled: bool = True
    created_at: str = ""


@dataclass
class BotStatistic:
    files_received: int = 0
    files_processed: int = 0
    files_failed: int = 0
    cuts_performed: int = 0
    covers_updated: int = 0
    lyrics_updated: int = 0
    unique_users: int = 0
    total_processed_bytes: int = 0

    @property
    def total_processed_mb(self) -> float:
        return round(self.total_processed_bytes / (1024 * 1024), 2)


@dataclass
class JobRecord:
    uuid: str
    user_id: int
    chat_id: int
    filename: str
    file_size: int
    status: str
    created_at: str
    updated_at: str


@dataclass
class WhitelistedUser:
    user_id: int
    username: Optional[str] = None
    reason: Optional[str] = None
    added_at: str = ""


@dataclass
class BannedUser:
    user_id: int
    username: Optional[str] = None
    reason: Optional[str] = None
    banned_at: str = ""


@dataclass
class AdminAuditLog:
    id: Optional[int] = None
    admin_id: int = 0
    action: str = ""
    target: Optional[str] = None
    details: Optional[str] = None
    created_at: str = ""


@dataclass
class BroadcastRecord:
    id: Optional[int] = None
    admin_id: int = 0
    source_chat_id: int = 0
    source_message_id: int = 0
    text_preview: Optional[str] = None
    total_targets: int = 0
    delivered_count: int = 0
    blocked_count: int = 0
    failed_count: int = 0
    status: str = "pending"
    created_at: str = ""
    completed_at: Optional[str] = None


