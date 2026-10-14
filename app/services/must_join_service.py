"""Must-join channel membership verification service with event-driven Redis caching."""

import logging
from typing import List, Optional, Tuple
from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from app.database.models import RequiredChannel
from app.database.repository import DatabaseRepository
from app.services.must_join_redis import MustJoinRedisClient

logger = logging.getLogger(__name__)

ALLOWED_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


class MustJoinService:
    """Verifies that users have joined mandatory broadcast channels using Redis caching & Telegram fallback."""

    def __init__(
        self,
        repository: DatabaseRepository,
        redis_client: Optional[MustJoinRedisClient] = None,
    ):
        self.repository = repository
        self.redis_client = redis_client

    async def is_known_user(self, user_id: int) -> bool:
        """Checks whether user is tracked in known users (write-amplification protection)."""
        if self.redis_client:
            return await self.redis_client.is_known_user(user_id)
        return True

    async def mark_user_known(self, user_id: int) -> None:
        """Registers user in known users set."""
        if self.redis_client:
            await self.redis_client.mark_user_known(user_id)

    async def record_chat_member_update(
        self,
        user_id: int,
        channel_id: str,
        status: str,
        timestamp: Optional[float] = None,
    ) -> bool:
        """Records a member status change in Redis with TTL and out-of-order rejection."""
        if self.redis_client:
            return await self.redis_client.set_cached_membership(
                user_id=user_id,
                channel_id=channel_id,
                status=status,
                update_timestamp=timestamp,
            )
        return True

    async def save_prompt_message(self, user_id: int, chat_id: int, message_id: int) -> None:
        """Stores the unjoined prompt message ID in Redis for future auto-cleanup."""
        if self.redis_client:
            await self.redis_client.save_must_join_prompt(
                user_id=user_id, chat_id=chat_id, message_id=message_id
            )

    async def get_and_clear_prompt_message(self, user_id: int) -> Optional[Tuple[int, int]]:
        """Retrieves and clears the prompt message location."""
        if self.redis_client:
            return await self.redis_client.get_and_clear_must_join_prompt(user_id)
        return None

    async def check_user_membership(
        self, bot: Bot, user_id: int
    ) -> Tuple[bool, List[RequiredChannel]]:
        """
        Check whether user_id is a member of all active required channels.
        Checks Redis cache first. If cache miss, verifies with bot.get_chat_member and caches the result.
        Returns: (has_joined_all, list_of_missing_channels).
        """
        required_channels = await self.repository.list_channels(enabled_only=True)
        if not required_channels:
            return True, []

        missing_channels: List[RequiredChannel] = []

        for channel in required_channels:
            # 1. Check Redis cache
            cached_status = None
            if self.redis_client:
                cached_status = await self.redis_client.get_cached_membership(
                    user_id=user_id, channel_id=channel.channel_id
                )
                if not cached_status and channel.username:
                    cached_status = await self.redis_client.get_cached_membership(
                        user_id=user_id, channel_id=channel.username
                    )

            if cached_status == "MEMBER":
                continue
            elif cached_status == "NOT_MEMBER":
                missing_channels.append(channel)
                continue

            # 2. Cache miss: verify with Telegram Bot API
            target = channel.channel_id
            if channel.username and not str(target).startswith("-100"):
                target = f"@{channel.username.lstrip('@')}"

            try:
                member = await bot.get_chat_member(chat_id=target, user_id=user_id)
                if member.status in ALLOWED_STATUSES:
                    if self.redis_client:
                        await self.redis_client.set_cached_membership(
                            user_id=user_id,
                            channel_id=channel.channel_id,
                            status="MEMBER",
                        )
                else:
                    missing_channels.append(channel)
                    if self.redis_client:
                        await self.redis_client.set_cached_membership(
                            user_id=user_id,
                            channel_id=channel.channel_id,
                            status="NOT_MEMBER",
                        )
            except Exception as e:
                logger.warning(
                    f"Could not verify membership for user {user_id} in {target}: {e}"
                )
                missing_channels.append(channel)
                if self.redis_client:
                    await self.redis_client.set_cached_membership(
                        user_id=user_id,
                        channel_id=channel.channel_id,
                        status="NOT_MEMBER",
                    )

        return len(missing_channels) == 0, missing_channels
