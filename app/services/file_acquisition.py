"""
Unified file acquisition service for Telegram Cloud and Local Bot API modes.

Security and Architecture:
- In Cloud mode, files are downloaded over standard HTTP via bot.download_file().
- In Local mode (--local), Telegram Local Bot API returns an absolute filesystem path
  pointing inside its storage directory (by default /var/lib/telegram-bot-api).
- Because SongTaggerBot shares the storage volume read-only (:ro), files are copied
  directly from disk with zero network bandwidth overhead.
- Security Boundary: Every path returned in Local mode is strictly resolved and verified
  to ensure it resides within the allowed root directory. Any path traversal attempt or
  path outside the root is rejected immediately with SecurityError.
- Shared-Volume Safety: The centralized volume may host data from multiple bots sharing
  the same Local Bot API stack. This service treats the mounted volume as strictly read-only,
  never mutates or deletes external files, and accesses only the specific file path returned
  by getFile for the active bot token.
"""

import logging
import os
from pathlib import Path
import shutil
from typing import Union

from aiogram import Bot
from aiogram.types import File

from app.config import Settings

logger = logging.getLogger(__name__)


class FileAcquisitionError(Exception):
    """Base exception for file acquisition failures."""
    pass


class SecurityError(FileAcquisitionError):
    """Raised when a path traversal or out-of-boundary file access is detected."""
    pass


class LocalFileAccessError(FileAcquisitionError):
    """Raised when Local Bot API file is not accessible in the mounted volume."""
    pass


class FileAcquisitionService:
    """Acquires files from Telegram in either Cloud or Local Bot API mode."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.allowed_root = Path(settings.local_bot_api_data_dir).resolve()

    async def acquire_file(
        self,
        bot: Bot,
        file_or_id: Union[str, File],
        destination: Path,
    ) -> Path:
        """
        Acquires a file from Telegram and copies/saves it to destination.

        :param bot: Active aiogram Bot instance.
        :param file_or_id: File object or Telegram file_id string.
        :param destination: Target Path on local scratchpad.
        :return: Resolved Path to the acquired local file.
        """
        # Ensure target directory exists
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Retrieve File info if given file_id string
        if isinstance(file_or_id, str):
            file_info = await bot.get_file(file_or_id)
        else:
            file_info = file_or_id

        if not file_info.file_path:
            raise FileAcquisitionError("Telegram getFile returned an empty file_path.")

        raw_path = file_info.file_path

        if self.settings.is_local_mode:
            return self._acquire_local_file(raw_path, destination)
        else:
            return await self._acquire_cloud_file(bot, raw_path, destination)

    def _acquire_local_file(self, raw_path: str, destination: Path) -> Path:
        """
        Copies a file directly from the mounted Local Bot API volume.
        Strictly enforces security path boundary and verifies file existence.
        """
        target_path = Path(raw_path).resolve()

        # Enforce security boundary: path MUST reside strictly inside allowed_root
        try:
            target_path.relative_to(self.allowed_root)
        except ValueError:
            logger.error(
                f"SECURITY ALERT: Path traversal attempt detected. "
                f"Path '{raw_path}' resolves to '{target_path}', "
                f"which is outside allowed root '{self.allowed_root}'."
            )
            raise SecurityError(
                f"Access denied: file path '{raw_path}' is outside allowed Local Bot API storage directory."
            )

        # Verify file existence and readability
        try:
            if not target_path.exists() or not target_path.is_file():
                # Diagnostic information for administrator
                root_exists = self.allowed_root.exists()
                root_is_dir = self.allowed_root.is_dir() if root_exists else False
                logger.error(
                    f"Local Bot API file not found on disk: '{target_path}'. "
                    f"Allowed root: '{self.allowed_root}' (exists={root_exists}, is_dir={root_is_dir}). "
                    f"Ensure the shared Docker volume 'telegram-bot-api-data' is mounted at "
                    f"'{self.allowed_root}:ro'."
                )
                raise LocalFileAccessError(
                    f"Local Bot API storage file is missing or inaccessible: '{target_path}'. "
                    f"Please verify that the volume 'telegram-bot-api-data' is mounted to '{self.allowed_root}:ro'."
                )
        except PermissionError as e:
            logger.error(
                f"Permission denied accessing Local Bot API file '{target_path}': {e}. "
                f"Ensure the bot process has read permissions for mounted volume '{self.allowed_root}'."
            )
            raise LocalFileAccessError(
                f"Permission denied accessing Local Bot API file: '{target_path}'. "
                f"Check user/group permissions for volume mount '{self.allowed_root}:ro'."
            ) from e

        # Copy directly via local filesystem (fast, zero network overhead)
        try:
            shutil.copy2(target_path, destination)
            logger.info(
                f"Successfully copied local file from '{target_path}' to '{destination}' "
                f"({destination.stat().st_size} bytes)."
            )
            return destination
        except Exception as e:
            logger.error(f"Failed to copy local file from '{target_path}' to '{destination}': {e}")
            raise FileAcquisitionError(f"Failed to copy local file: {e}") from e

    async def _acquire_cloud_file(self, bot: Bot, raw_path: str, destination: Path) -> Path:
        """
        Downloads a file from Telegram Cloud servers over HTTP via aiogram.
        """
        logger.info(f"Downloading file over HTTP from Telegram Cloud: '{raw_path}' to '{destination}'")
        try:
            await bot.download_file(raw_path, destination=destination)
            return destination
        except Exception as e:
            logger.error(f"HTTP download failed for '{raw_path}': {e}")
            raise FileAcquisitionError(f"HTTP download failed: {e}") from e
