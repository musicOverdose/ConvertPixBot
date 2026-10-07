"""Must-join channel membership verification service."""

import logging
from typing import List, Tuple
from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from app.database.models import RequiredChannel
from app.database.repository import DatabaseRepository

logger = logging.getLogger(__name__)

ALLOWED_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


class MustJoinService:
    """Verifies that users have joined mandatory broadcast channels."""

    def __init__(self, repository: DatabaseRepository):
        self.repository = repository

    async def check_user_membership(
        self, bot: Bot, user_id: int
    ) -> Tuple[bool, List[RequiredChannel]]:
        """
        Check whether user_id is a member of all active required channels.
        Returns: (has_joined_all, list_of_missing_channels).
        """
        required_channels = await self.repository.list_channels(enabled_only=True)
        if not required_channels:
            return True, []

        missing_channels: List[RequiredChannel] = []

        for channel in required_channels:
            target = channel.channel_id
            if channel.username and not str(target).startswith("-100"):
                target = f"@{channel.username.lstrip('@')}"

            try:
                member = await bot.get_chat_member(chat_id=target, user_id=user_id)
                if member.status not in ALLOWED_STATUSES:
                    missing_channels.append(channel)
            except Exception as e:
                logger.warning(
                    f"Could not verify membership for user {user_id} in {target}: {e}"
                )
                # If bot cannot verify (e.g. not admin in private channel), report as missing
                missing_channels.append(channel)

        return len(missing_channels) == 0, missing_channels
