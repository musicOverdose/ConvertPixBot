"""Service coordinating safe configuration of Cloud vs Centralized Local Bot API modes."""

import asyncio
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

from aiogram import Bot

from app.config import Settings
from app.database.repository import DatabaseRepository

logger = logging.getLogger(__name__)


class ApiModeManager:
    """
    Coordinates safe configuration of Cloud vs Centralized Local Bot API modes.

    IMPORTANT: Moving a Telegram bot between Bot API servers (e.g. Cloud <-> Local or
    Local <-> different Local server) requires proper Telegram `logOut` and bot restart/reconnect.
    In-memory session hot-switching (`bot.session.api = ...`) is not performed.
    """

    def __init__(
        self,
        bot: Optional[Bot],
        settings: Settings,
        repository: DatabaseRepository,
        running_mode: Optional[str] = None,
        running_endpoint: Optional[str] = None,
    ):
        self.bot = bot
        self.settings = settings
        self.repository = repository
        self.running_mode = (running_mode or settings.telegram_api_mode).lower().strip()
        self.running_endpoint = (running_endpoint or settings.effective_api_base_url).strip().rstrip("/")
        self._lock = asyncio.Lock()

    def get_running_mode(self) -> str:
        """Returns the mode with which the currently running bot session was started ('cloud' or 'local')."""
        return self.running_mode

    def get_running_endpoint(self) -> str:
        """Returns the endpoint URL the currently running bot session is connected to."""
        return self.running_endpoint

    def get_configured_mode(self) -> str:
        """Returns the currently configured mode in settings/DB ('cloud' or 'local')."""
        return "local" if self.settings.is_local_mode else "cloud"

    def get_configured_endpoint(self) -> str:
        """Returns the currently configured API base URL."""
        return self.settings.effective_api_base_url.strip().rstrip("/")

    # Backwards-compatible aliases for legacy callers
    def get_current_mode(self) -> str:
        return self.get_configured_mode()

    def get_current_endpoint(self) -> str:
        return self.get_configured_endpoint()

    def is_restart_required(self) -> bool:
        """
        True if the configured mode or configured endpoint differs from the currently running bot instance.
        """
        return (
            self.get_configured_mode() != self.get_running_mode()
            or self.get_configured_endpoint() != self.get_running_endpoint()
        )

    def is_migration_required(self) -> bool:
        """
        True if the configured endpoint represents a different Bot API server from the running server.
        Telegram Bot API requires manual logOut on the previous server before reconnecting to a new one.
        """
        return self.get_configured_endpoint() != self.get_running_endpoint()

    @staticmethod
    def get_migration_instructions() -> str:
        """Returns formatted HTML migration guide."""
        return (
            "⚠️ <b>Telegram Bot API Migration Required</b>\n\n"
            "Moving between Telegram Bot API servers requires proper session termination.\n"
            "<b>Before restarting:</b>\n"
            "1. Stop the bot.\n"
            "2. Call Telegram <code>logOut</code> through the current/old Bot API server.\n"
            "3. Start the bot with the new endpoint."
        )

    @staticmethod
    def get_migration_instructions_text() -> str:
        """Returns plain-text migration guide for CLI/logs."""
        return (
            "⚠️ Telegram Bot API migration required\n\n"
            "Before restarting:\n"
            "1. Stop the bot.\n"
            "2. Call Telegram logOut through the current/old Bot API server.\n"
            "3. Start the bot with the new endpoint."
        )

    @staticmethod
    def validate_local_url(url: str) -> bool:
        """Validates that a URL is a valid HTTP/HTTPS endpoint."""
        try:
            parsed = urlparse(url.strip())
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    async def configure_mode(
        self,
        new_mode: str,
        new_base_url: Optional[str] = None,
        admin_id: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Persists the target API mode and endpoint to settings/database.
        Does NOT hot-switch bot.session.api dynamically.
        Flags whether restart and/or Telegram migration are required.
        """
        new_mode = new_mode.lower().strip()
        if new_mode not in ("cloud", "local"):
            return False, f"Invalid API mode: '{new_mode}'. Must be 'cloud' or 'local'."

        async with self._lock:
            if new_mode == "local":
                target_url = (new_base_url or self.settings.telegram_api_base_url).strip().rstrip("/")
                if not target_url or target_url == "https://api.telegram.org":
                    target_url = "http://telegram-bot-api:8081"

                if not self.validate_local_url(target_url):
                    return False, f"Invalid Local Bot API URL: '{target_url}'. Must start with http:// or https:// with a valid host."
            else:
                target_url = "https://api.telegram.org"

            # Persist configuration to database
            await self.repository.set_system_setting("telegram_api_mode", new_mode)
            if new_mode == "local":
                await self.repository.set_system_setting("telegram_api_base_url", target_url)

            # Update in-memory settings
            self.settings.telegram_api_mode = new_mode
            if new_mode == "local":
                self.settings.telegram_api_base_url = target_url

            # Adjust application file size limits sensibly
            if new_mode == "cloud":
                if self.settings.max_input_mb > 20:
                    self.settings.max_input_mb = 20
                    await self.repository.set_system_setting("max_input_mb", "20")
                if self.settings.max_output_mb > 50:
                    self.settings.max_output_mb = 50
                    await self.repository.set_system_setting("max_output_mb", "50")
            elif new_mode == "local":
                if self.settings.max_input_mb <= 20:
                    self.settings.max_input_mb = 2000
                    await self.repository.set_system_setting("max_input_mb", "2000")
                if self.settings.max_output_mb <= 50:
                    self.settings.max_output_mb = 2000
                    await self.repository.set_system_setting("max_output_mb", "2000")

            mig_req = self.is_migration_required()
            rst_req = self.is_restart_required()

            # Record in admin audit log
            if admin_id is not None:
                audit_note = "Migration required" if mig_req else ("Restart required" if rst_req else "Applied")
                await self.repository.log_audit_action(
                    admin_id=admin_id,
                    action="configure_api_mode",
                    details=f"Configured {new_mode} mode ({target_url}). {audit_note}",
                )

            # Build response message
            if mig_req:
                msg = (
                    f"Configured API mode saved as <b>{new_mode.upper()}</b> (<code>{target_url}</code>).\n\n"
                    f"⚠️ <b>Telegram Bot API migration required!</b>\n"
                    f"Current server: <code>{self.running_endpoint}</code>\n"
                    f"Target server: <code>{target_url}</code>\n\n"
                    f"<b>Before restarting:</b>\n"
                    f"1. Stop the bot.\n"
                    f"2. Call Telegram <code>logOut</code> through current server.\n"
                    f"3. Start the bot with new endpoint."
                )
            elif rst_req:
                msg = (
                    f"Configured API mode saved as <b>{new_mode.upper()}</b> (<code>{target_url}</code>).\n\n"
                    f"⚠️ <b>Restart required to apply changes.</b>"
                )
            else:
                msg = f"Configured API mode matches active running mode ({new_mode.upper()})."

            return True, msg

    async def switch_mode(
        self,
        new_mode: str,
        new_base_url: Optional[str] = None,
        admin_id: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Backwards-compatible alias for configure_mode."""
        return await self.configure_mode(new_mode, new_base_url, admin_id)

    async def update_local_url(self, new_url: str, admin_id: Optional[int] = None) -> Tuple[bool, str]:
        """Updates the configured local API URL."""
        new_url = new_url.strip().rstrip("/")
        if not self.validate_local_url(new_url):
            return False, f"Invalid URL: '{new_url}'. Must start with http:// or https:// with a valid host."

        async with self._lock:
            self.settings.telegram_api_base_url = new_url
            await self.repository.set_system_setting("telegram_api_base_url", new_url)

            mig_req = self.is_migration_required()
            rst_req = self.is_restart_required()

            if admin_id is not None:
                await self.repository.log_audit_action(
                    admin_id=admin_id,
                    action="update_setting",
                    details=f"Updated Local Bot API URL to {new_url}" + (" (Migration required)" if mig_req else ""),
                )

            if mig_req:
                msg = (
                    f"Local Bot API URL set to <code>{new_url}</code>.\n\n"
                    f"⚠️ <b>Telegram Bot API migration required!</b>\n"
                    f"Current server: <code>{self.running_endpoint}</code>\n"
                    f"Target server: <code>{new_url}</code>\n\n"
                    f"<b>Before restarting:</b>\n"
                    f"1. Stop the bot.\n"
                    f"2. Call Telegram <code>logOut</code> on old server.\n"
                    f"3. Start the bot with new endpoint."
                )
            elif rst_req:
                msg = f"Local Bot API URL set to <code>{new_url}</code>.\n⚠️ Restart required to apply changes."
            else:
                msg = f"Local Bot API URL set to <code>{new_url}</code>."

            return True, msg

    async def reset_to_env_defaults(self, admin_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Resets dynamic overrides back to .env values.
        Does NOT hot-switch bot.session.api dynamically.
        """
        async with self._lock:
            # Clear database overrides
            for key in (
                "telegram_api_mode",
                "telegram_api_base_url",
                "max_input_mb",
                "max_output_mb",
                "show_technical_info",
                "send_cover_separately",
            ):
                await self.repository.set_system_setting(key, "")

            # Reload fresh settings from .env / environment
            candidate_settings = Settings()

            self.settings.telegram_api_mode = candidate_settings.telegram_api_mode
            self.settings.telegram_api_base_url = candidate_settings.telegram_api_base_url
            self.settings.max_input_mb = candidate_settings.max_input_mb
            self.settings.max_output_mb = candidate_settings.max_output_mb
            self.settings.show_technical_info = candidate_settings.show_technical_info
            self.settings.send_cover_separately = candidate_settings.send_cover_separately

            try:
                from app.config import reload_settings
                reload_settings()
            except Exception:
                pass

            mig_req = self.is_migration_required()
            rst_req = self.is_restart_required()

            if admin_id is not None:
                await self.repository.log_audit_action(
                    admin_id=admin_id,
                    action="reset_settings",
                    details=f"Reset settings to .env defaults ({candidate_settings.telegram_api_mode})."
                    + (" Migration required" if mig_req else (" Restart required" if rst_req else "")),
                )

            if mig_req:
                msg = (
                    f"Settings reset to .env defaults ({candidate_settings.telegram_api_mode.upper()}).\n\n"
                    f"⚠️ <b>Telegram Bot API migration required!</b>\n"
                    f"Current server: <code>{self.running_endpoint}</code>\n"
                    f"Target server: <code>{self.get_configured_endpoint()}</code>\n\n"
                    f"<b>Before restarting:</b>\n"
                    f"1. Stop the bot.\n"
                    f"2. Call Telegram <code>logOut</code> on old server.\n"
                    f"3. Start the bot with new endpoint."
                )
            elif rst_req:
                msg = (
                    f"Settings reset to .env defaults ({candidate_settings.telegram_api_mode.upper()}).\n\n"
                    f"⚠️ <b>Restart required to apply API server changes.</b>"
                )
            else:
                msg = f"Settings reset to .env defaults ({candidate_settings.telegram_api_mode.upper()})!"

            return True, msg

