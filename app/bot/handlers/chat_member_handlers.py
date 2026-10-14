"""Event-driven Telegram ChatMemberUpdated handler for real-time auto-unblock."""

import logging
import time
from typing import Optional
from aiogram import Router, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated

from app.services.must_join_service import MustJoinService, ALLOWED_STATUSES
from app.services.message_service import MessageService

logger = logging.getLogger(__name__)

router = Router(name="chat_member_router")


@router.chat_member()
async def handle_chat_member_updated(
    event: ChatMemberUpdated,
    bot: Bot,
    must_join_service: MustJoinService,
    message_service: Optional[MessageService] = None,
) -> None:
    """
    Ingests real-time channel membership updates from Telegram.
    - Updates Redis cache with 24h TTL (MEMBER) or 30s TTL (NOT_MEMBER).
    - Protects against out-of-order updates using event timestamp.
    - Protects against write-amplification by checking {bot_prefix}:known_users.
    - Seamlessly cleans up must-join prompt and delivers Welcome Message on completion.
    """
    new_member = event.new_chat_member
    target_user = getattr(new_member, "user", None)
    if not target_user or target_user.is_bot:
        return

    user_id = target_user.id
    channel_id = str(event.chat.id)
    status_enum = getattr(new_member, "status", None)
    event_timestamp = event.date.timestamp() if getattr(event, "date", None) else time.time()

    # 1. Write-amplification protection: only record users present in known_users
    is_known = await must_join_service.is_known_user(user_id)
    if not is_known:
        logger.debug(f"Ignoring ChatMemberUpdated for unknown user {user_id} in {channel_id}")
        return

    # 2. Determine member status
    is_member = status_enum in ALLOWED_STATUSES
    status_str = "MEMBER" if is_member else "NOT_MEMBER"

    # 3. Update Redis cache with out-of-order protection
    accepted = await must_join_service.record_chat_member_update(
        user_id=user_id,
        channel_id=channel_id,
        status=status_str,
        timestamp=event_timestamp,
    )
    if not accepted:
        logger.debug(f"Rejected out-of-order ChatMemberUpdated for user {user_id}")
        return

    logger.info(
        f"Ingested ChatMemberUpdated: user {user_id} in {channel_id} -> {status_str}"
    )

    # 4. If user joined, check if all required channels are now satisfied
    if is_member:
        has_joined_all, missing = await must_join_service.check_user_membership(bot, user_id)
        if has_joined_all:
            # Check for pending prompt message to clean up and unblock
            prompt = await must_join_service.get_and_clear_prompt_message(user_id)
            chat_id_to_send = user_id
            if prompt:
                prompt_chat_id, prompt_message_id = prompt
                chat_id_to_send = prompt_chat_id
                try:
                    await bot.delete_message(chat_id=prompt_chat_id, message_id=prompt_message_id)
                    logger.info(f"Cleaned up must-join prompt {prompt_message_id} for user {user_id}")
                except Exception as e:
                    logger.debug(f"Could not delete must-join prompt for user {user_id}: {e}")

            # Deliver Welcome Message to seamlessly unblock user
            try:
                if message_service:
                    welcome_text = await message_service.get_welcome_message(target_user)
                else:
                    from app.services.message_service import DEFAULT_WELCOME_MESSAGE, MessageService as MS
                    welcome_text = MS.render_template(DEFAULT_WELCOME_MESSAGE, target_user)

                await bot.send_message(chat_id=chat_id_to_send, text=welcome_text, parse_mode="HTML")
                logger.info(f"Successfully auto-unblocked and delivered Welcome Message to user {user_id}")
            except Exception as e:
                logger.warning(f"Could not send welcome message to auto-unblocked user {user_id}: {e}")
