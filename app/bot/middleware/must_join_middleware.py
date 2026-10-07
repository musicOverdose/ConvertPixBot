"""Middleware to enforce mandatory channel memberships."""

from typing import Any, Awaitable, Callable, Dict, Optional
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.keyboards.must_join_menu import get_must_join_keyboard
from app.services.message_service import MessageService
from app.services.must_join_service import MustJoinService


class MustJoinMiddleware(BaseMiddleware):
    """Enforces must-join requirements before allowing audio processing."""

    def __init__(
        self,
        must_join_service: MustJoinService,
        message_service: Optional[MessageService] = None,
    ):
        super().__init__()
        self.must_join_service = must_join_service
        self.message_service = message_service

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Check user ID from Message or CallbackQuery
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        bot = data["bot"]
        settings = data.get("settings")

        # Bypass for configured administrators
        if settings and settings.is_admin(user.id):
            return await handler(event, data)

        repo = self.must_join_service.repository

        # Check if user is banned
        if await repo.is_banned(user.id):
            if isinstance(event, Message):
                await event.reply(
                    "🚫 <b>Access Denied</b>\n\nYou have been banned from using this bot.",
                    parse_mode="HTML",
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("🚫 You have been banned from using this bot.", show_alert=True)
            return None

        # Check if user is whitelisted (bypasses must-join requirement)
        if await repo.is_whitelisted(user.id):
            return await handler(event, data)

        # Allow must_join_verify callback to be processed by its handler
        if isinstance(event, CallbackQuery) and event.data == "must_join_verify":
            return await handler(event, data)

        # Verify membership
        has_joined, missing = await self.must_join_service.check_user_membership(
            bot=bot, user_id=user.id
        )

        if not has_joined:
            kb = get_must_join_keyboard(missing)
            if self.message_service:
                text = await self.message_service.get_must_join_message(user)
            else:
                from app.services.message_service import DEFAULT_MUST_JOIN_MESSAGE, MessageService as MS
                text = MS.render_template(DEFAULT_MUST_JOIN_MESSAGE, user)
            if isinstance(event, Message):
                await event.reply(text, reply_markup=kb, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer("Please join the required channels first.", show_alert=True)
                if event.message:
                    await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return None

        return await handler(event, data)

