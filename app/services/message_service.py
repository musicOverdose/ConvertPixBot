"""
Message customization service for SongTaggerBot.

Supports customizable /start (welcome), must-join, and /help messages.
Persists custom templates in SQLite database (system_settings table).
Validates HTML against Telegram Bot API formatting specifications.
Provides safe placeholder substitution for {first_name}, {username}, {user_id}, {bot_name}.
"""

from html.parser import HTMLParser
import logging
from typing import Optional, Union

from aiogram.types import User

from app.database.repository import DatabaseRepository

logger = logging.getLogger(__name__)

# Supported Telegram HTML tags
ALLOWED_TELEGRAM_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "span", "tg-spoiler", "a", "code", "pre", "blockquote", "expandable-quote"
}

ALLOWED_PLACEHOLDERS = {"first_name", "username", "user_id", "bot_name"}

# Default Built-In Templates
DEFAULT_WELCOME_MESSAGE = "Welcome {first_name}! Send an audio file to start editing tags."
DEFAULT_MUST_JOIN_MESSAGE = (
    "👋 Hello <b>{first_name}</b>!\n\n"
    "Please join our channel(s) below to use <b>SongTaggerBot</b>.\n"
    "After joining, tap <b>🔄 I've joined</b> to start using the bot!"
)
DEFAULT_HELP_MESSAGE = "Send an audio file to view and edit its metadata tags."

MESSAGE_DEFAULTS = {
    "welcome": DEFAULT_WELCOME_MESSAGE,
    "must_join": DEFAULT_MUST_JOIN_MESSAGE,
    "help": DEFAULT_HELP_MESSAGE,
}

MESSAGE_TITLES = {
    "welcome": "Welcome Message (/start)",
    "must_join": "Must-Join Channel Prompt",
    "help": "Help Message (/help)",
}


class TelegramHTMLValidator(HTMLParser):
    """Validates that markup adheres strictly to Telegram HTML subset."""

    def __init__(self):
        super().__init__()
        self.errors: list[str] = []
        self.tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        if tag_lower not in ALLOWED_TELEGRAM_TAGS:
            self.errors.append(f"Unsupported tag <{tag}>. Only Telegram HTML tags are allowed.")
            return

        for attr, val in attrs:
            attr_lower = attr.lower()
            if tag_lower == "a" and attr_lower == "href":
                continue
            elif tag_lower == "span" and attr_lower == "class" and val == "tg-spoiler":
                continue
            elif tag_lower in ("pre", "code") and attr_lower == "language":
                continue
            else:
                self.errors.append(f"Attribute '{attr}' is not allowed on <{tag}>.")

        self.tag_stack.append(tag_lower)

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower not in ALLOWED_TELEGRAM_TAGS:
            return

        if not self.tag_stack or self.tag_stack[-1] != tag_lower:
            self.errors.append(f"Mismatched closing tag </{tag}>.")
        else:
            self.tag_stack.pop()

    def close(self) -> None:
        super().close()
        if self.tag_stack:
            unclosed = ", ".join(f"<{t}>" for t in self.tag_stack)
            self.errors.append(f"Unclosed tag(s): {unclosed}")


class MessageService:
    """Manages customizable bot messages with persistence and placeholder formatting."""

    def __init__(self, repository: DatabaseRepository):
        self.repository = repository

    @staticmethod
    def validate_telegram_html(text: str) -> tuple[bool, str]:
        """Validates that text conforms to Telegram-supported HTML and balanced tags."""
        # Replace allowed placeholders temporarily with dummy text to test HTML parsing
        test_text = text
        for placeholder in ALLOWED_PLACEHOLDERS:
            test_text = test_text.replace(f"{{{placeholder}}}", "SAMPLE")

        validator = TelegramHTMLValidator()
        try:
            validator.feed(test_text)
            validator.close()
        except Exception as e:
            return False, f"HTML parse error: {e}"

        if validator.errors:
            return False, validator.errors[0]

        return True, ""

    @staticmethod
    def render_template(
        template: str,
        user: Optional[User] = None,
        bot_name: str = "SongTaggerBot",
    ) -> str:
        """
        Safely substitutes placeholders {first_name}, {username}, {user_id}, {bot_name}.
        Does not crash on unknown placeholders or stray curly braces.
        """
        first_name = ""
        if user and hasattr(user, "first_name") and isinstance(user.first_name, str):
            first_name = user.first_name

        username = ""
        if user and hasattr(user, "username") and isinstance(user.username, str):
            username = f"@{user.username}"

        user_id = ""
        if user and hasattr(user, "id"):
            val_id = getattr(user, "id")
            if isinstance(val_id, (int, str)):
                user_id = str(val_id)

        replacements = {
            "{first_name}": str(first_name),
            "{username}": str(username),
            "{user_id}": str(user_id),
            "{bot_name}": str(bot_name),
        }

        rendered = template
        for key, val in replacements.items():
            rendered = rendered.replace(key, str(val))

        return rendered

    async def get_raw_message(self, msg_key: str) -> tuple[str, bool]:
        """
        Returns (template, is_custom).
        If no custom value exists in DB, returns built-in default with is_custom=False.
        """
        if msg_key not in MESSAGE_DEFAULTS:
            raise ValueError(f"Unknown message key: {msg_key}")

        custom_val = await self.repository.get_system_setting(f"msg_{msg_key}", "")
        if custom_val.strip():
            return custom_val, True
        return MESSAGE_DEFAULTS[msg_key], False

    async def get_welcome_message(
        self,
        user: Optional[User] = None,
        bot_name: str = "SongTaggerBot",
    ) -> str:
        """Returns the rendered welcome message for /start."""
        template, _ = await self.get_raw_message("welcome")
        return self.render_template(template, user=user, bot_name=bot_name)

    async def get_must_join_message(
        self,
        user: Optional[User] = None,
        bot_name: str = "SongTaggerBot",
    ) -> str:
        """Returns the rendered must-join channel prompt message."""
        template, _ = await self.get_raw_message("must_join")
        return self.render_template(template, user=user, bot_name=bot_name)

    async def get_help_message(
        self,
        user: Optional[User] = None,
        bot_name: str = "SongTaggerBot",
    ) -> str:
        """Returns the rendered help message for /help."""
        template, _ = await self.get_raw_message("help")
        return self.render_template(template, user=user, bot_name=bot_name)

    async def set_message(
        self,
        msg_key: str,
        text: str,
        admin_id: int,
    ) -> tuple[bool, str]:
        """
        Sets a customized message in the database.
        Validates HTML formatting and logs audit trail.
        """
        if msg_key not in MESSAGE_DEFAULTS:
            return False, f"Unknown message key: '{msg_key}'"

        text = text.strip()
        if not text:
            return False, "Message content cannot be empty."

        valid, err = self.validate_telegram_html(text)
        if not valid:
            return False, f"Invalid Telegram HTML formatting: {err}"

        # Persist in database
        db_key = f"msg_{msg_key}"
        await self.repository.set_system_setting(db_key, text)

        # Audit logging
        await self.repository.log_audit_action(
            admin_id=admin_id,
            action="update_custom_message",
            target=msg_key,
            details=f"Updated {MESSAGE_TITLES.get(msg_key, msg_key)} ({len(text)} chars)",
        )
        logger.info(f"Admin {admin_id} updated custom message '{msg_key}'.")
        return True, "Message updated successfully."

    async def reset_message(
        self,
        msg_key: str,
        admin_id: int,
    ) -> tuple[bool, str]:
        """
        Resets a customized message to its built-in default by removing
        the database row.
        """
        if msg_key not in MESSAGE_DEFAULTS:
            return False, f"Unknown message key: '{msg_key}'"

        db_key = f"msg_{msg_key}"
        deleted = await self.repository.delete_system_setting(db_key)

        await self.repository.log_audit_action(
            admin_id=admin_id,
            action="reset_custom_message",
            target=msg_key,
            details=f"Reset {MESSAGE_TITLES.get(msg_key, msg_key)} to default",
        )
        logger.info(f"Admin {admin_id} reset custom message '{msg_key}' to default.")
        return True, "Message reset to default."

    async def get_status_overview(self) -> dict[str, dict]:
        """Returns status of all managed messages (title, is_custom, length, preview)."""
        result = {}
        for key, title in MESSAGE_TITLES.items():
            text, is_custom = await self.get_raw_message(key)
            preview = text[:80] + ("..." if len(text) > 80 else "")
            result[key] = {
                "title": title,
                "is_custom": is_custom,
                "length": len(text),
                "preview": preview,
                "full_text": text,
            }
        return result
