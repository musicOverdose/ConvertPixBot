"""Application configuration using Pydantic Settings."""

import os
from pathlib import Path
from typing import Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_default_data_dir() -> Path:
    target = Path('/data')
    try:
        if target.exists() and os.access(target, os.W_OK):
            return target
    except Exception:
        pass
    return Path('./data').resolve()


def get_default_temp_dir() -> Path:
    target = Path('/tmp/bot-app')
    try:
        target.mkdir(parents=True, exist_ok=True)
        if os.access(target, os.W_OK):
            return target
    except Exception:
        pass
    return Path('./temp/bot-app').resolve()


class Settings(BaseSettings):
    """Central configuration for Telegram Bot."""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    # Telegram Bot Token & Identity
    bot_token: str = Field(default='', description='Telegram Bot API Token')
    bot_name: str = Field(default='Convert Pix Bot', description='Display name of the bot')

    # Administrators (list of integer Telegram IDs)
    admin_ids: list[int] = Field(default_factory=list, description='Admin Telegram IDs')

    # Size limits in megabytes
    max_input_mb: int = Field(default=50, ge=1, le=2000, description='Max input file size in MB')
    max_output_mb: int = Field(default=50, ge=1, le=2000, description='Max output file size in MB')

    # Concurrency and Job TTL
    max_concurrent_jobs: int = Field(default=2, ge=1, le=64, description='Max concurrent processing workers')
    max_user_concurrent_jobs: int = Field(default=1, ge=1, le=10, description='Max concurrent jobs per user')
    max_global_concurrent_jobs: int = Field(default=10, ge=1, le=128, description='Global maximum concurrent jobs')
    job_ttl_minutes: int = Field(default=30, ge=1, le=1440, description='TTL in minutes for temporary jobs')

    # Abuse protection and timeouts
    rate_limit_uploads_per_minute: int = Field(default=10, ge=1, le=120, description='Max operations per minute per user')

    # Directory Paths & Backups
    data_dir: Path = Field(default_factory=get_default_data_dir, description='Path to persistent data directory')
    temp_dir: Path = Field(default_factory=get_default_temp_dir, description='Path to temporary processing directory')
    backup_retention_days: int = Field(default=7, ge=1, le=90, description='Days to retain database backups')

    # Logging
    log_level: str = Field(default='INFO', description='Logging level')

    # Telegram Bot API Mode & Endpoint (Dual Mode: Cloud vs Centralized Local)
    telegram_api_mode: str = Field(
        default='local',
        description="API server mode: 'cloud' (official api.telegram.org) or 'local' (centralized Local Bot API)",
    )
    telegram_api_base_url: str = Field(
        default='http://telegram-bot-api:8081',
        description='Telegram Bot API base URL',
    )
    local_bot_api_data_dir: Path = Field(
        default=Path('/var/lib/telegram-bot-api'),
        description='Path to mounted Local Bot API storage directory',
    )

    # UI and delivery flags
    show_technical_info: bool = Field(
        default=True,
        description='Show image inspection details in metadata message',
    )
    send_cover_separately: bool = Field(
        default=True,
        description='Send visual preview photo for image formats',
    )

    @property
    def is_local_mode(self) -> bool:
        return self.telegram_api_mode.lower().strip() == 'local'

    @property
    def effective_api_base_url(self) -> str:
        if self.is_local_mode:
            url = self.telegram_api_base_url.strip().rstrip('/')
            if not url or url == 'https://api.telegram.org':
                return 'http://telegram-bot-api:8081'
            return url
        return 'https://api.telegram.org'

    @field_validator('admin_ids', mode='before')
    @classmethod
    def parse_admin_ids(cls, v: Union[str, list[int], int, None]) -> list[int]:
        if v is None or v == '':
            return []
        if isinstance(v, int):
            return [v]
        if isinstance(v, list):
            return [int(item) for item in v if str(item).strip()]
        if isinstance(v, str):
            res = []
            for item in v.split(','):
                item_str = item.strip()
                if item_str.isdigit() or (item_str.startswith('-') and item_str[1:].isdigit()):
                    res.append(int(item_str))
            return res
        return []

    @property
    def max_input_bytes(self) -> int:
        return self.max_input_mb * 1024 * 1024

    @property
    def max_output_bytes(self) -> int:
        return self.max_output_mb * 1024 * 1024

    @property
    def db_path(self) -> Path:
        return self.data_dir / 'bot.db'

    @property
    def jobs_dir(self) -> Path:
        return self.temp_dir / 'jobs'

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / 'backups'

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = Settings()
    return _settings
