"""Event-driven Redis client for must-join caching and state."""

import logging
import time
from typing import Optional, Tuple, Any

try:
    import redis.asyncio as aioredis
    from redis.exceptions import RedisError
except ImportError:
    aioredis = None  # type: ignore
    RedisError = Exception  # type: ignore

logger = logging.getLogger(__name__)

MEMBER_CACHE_TTL = 86400  # 24 hours fixed TTL
NOT_MEMBER_CACHE_TTL = 30  # 30 seconds TTL
PROMPT_MSG_TTL = 86400  # 24 hours TTL


class MustJoinRedisClient:
    """Manages Redis connection, caching, out-of-order protection, and prompt cleanup."""

    def __init__(
        self,
        redis_url: str = "redis://telegram-redis:6379/1",
        bot_prefix: str = "convertpix",
        client: Optional[Any] = None,
    ):
        self.redis_url = redis_url
        self.bot_prefix = bot_prefix.strip().rstrip(":")
        self._client: Optional[Any] = client
        self._is_connected = client is not None

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._client is not None

    async def connect(self) -> bool:
        """Connects to Redis server with ping verification."""
        if self._client is not None:
            self._is_connected = True
            return True

        if aioredis is None:
            logger.warning("redis-py is not installed. MustJoinRedisClient will operate in offline mode.")
            return False

        try:
            self._client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=3.0,
                socket_connect_timeout=3.0,
            )
            await self._client.ping()
            self._is_connected = True
            logger.info(f"MustJoinRedisClient connected to Redis: {self.redis_url} (prefix: {self.bot_prefix})")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to Redis at {self.redis_url}: {e}. Operating in fallback mode.")
            self._is_connected = False
            return False

    async def close(self) -> None:
        """Closes the Redis connection."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
            self._is_connected = False
            logger.info("MustJoinRedisClient connection closed.")

    def _channel_key(self, user_id: int, channel_id: str) -> str:
        clean_ch = str(channel_id).strip().lstrip("@")
        return f"{self.bot_prefix}:must_join:{user_id}:{clean_ch}"

    def _channel_ts_key(self, user_id: int, channel_id: str) -> str:
        clean_ch = str(channel_id).strip().lstrip("@")
        return f"{self.bot_prefix}:must_join_ts:{user_id}:{clean_ch}"

    def _known_users_key(self) -> str:
        return f"{self.bot_prefix}:known_users"

    def _prompt_msg_key(self, user_id: int) -> str:
        return f"{self.bot_prefix}:must_join_msg:{user_id}"

    # --- Write-Amplification Protection (Known Users) ---

    async def is_known_user(self, user_id: int) -> bool:
        """Checks if user has interacted with the bot before."""
        if not self.is_connected:
            return True  # Fallback to permissive if Redis unavailable
        try:
            return bool(await self._client.sismember(self._known_users_key(), str(user_id)))
        except RedisError as e:
            logger.debug(f"Redis error checking known user {user_id}: {e}")
            return True

    async def mark_user_known(self, user_id: int) -> None:
        """Adds user to known users set."""
        if not self.is_connected:
            return
        try:
            await self._client.sadd(self._known_users_key(), str(user_id))
        except RedisError as e:
            logger.debug(f"Redis error marking user {user_id} known: {e}")

    # --- Membership Caching & Out-of-Order Protection ---

    async def get_cached_membership(self, user_id: int, channel_id: str) -> Optional[str]:
        """
        Retrieves cached membership status.
        Returns: 'MEMBER', 'NOT_MEMBER', or None on cache miss.
        """
        if not self.is_connected:
            return None
        try:
            val = await self._client.get(self._channel_key(user_id, channel_id))
            if val in ("MEMBER", "NOT_MEMBER"):
                return val
            return None
        except RedisError as e:
            logger.debug(f"Redis error getting membership cache for {user_id}: {e}")
            return None

    async def set_cached_membership(
        self,
        user_id: int,
        channel_id: str,
        status: str,
        update_timestamp: Optional[float] = None,
    ) -> bool:
        """
        Updates cached membership status with appropriate TTL and out-of-order rejection.
        - MEMBER: 24h fixed TTL.
        - NOT_MEMBER: 30s TTL.
        Returns: True if accepted and cached, False if rejected out-of-order.
        """
        if not self.is_connected:
            return True

        key = self._channel_key(user_id, channel_id)
        ts_key = self._channel_ts_key(user_id, channel_id)
        current_ts = update_timestamp or time.time()

        try:
            # Out-of-order check
            if update_timestamp is not None:
                existing_ts = await self._client.get(ts_key)
                if existing_ts:
                    try:
                        if float(existing_ts) > update_timestamp:
                            logger.debug(
                                f"Rejected out-of-order update for user {user_id} in {channel_id}: "
                                f"incoming {update_timestamp} < existing {existing_ts}"
                            )
                            return False
                    except ValueError:
                        pass

            ttl = MEMBER_CACHE_TTL if status == "MEMBER" else NOT_MEMBER_CACHE_TTL
            pipe = self._client.pipeline()
            pipe.set(key, status, ex=ttl)
            pipe.set(ts_key, str(current_ts), ex=ttl)
            await pipe.execute()
            return True
        except RedisError as e:
            logger.debug(f"Redis error setting membership cache for {user_id}: {e}")
            return False

    # --- Real-Time Prompt Message Tracking ---

    async def save_must_join_prompt(self, user_id: int, chat_id: int, message_id: int) -> None:
        """Saves the must-join prompt message location for subsequent auto-cleanup."""
        if not self.is_connected:
            return
        try:
            key = self._prompt_msg_key(user_id)
            val = f"{chat_id}:{message_id}"
            await self._client.set(key, val, ex=PROMPT_MSG_TTL)
        except RedisError as e:
            logger.debug(f"Redis error saving prompt message for user {user_id}: {e}")

    async def get_and_clear_must_join_prompt(self, user_id: int) -> Optional[Tuple[int, int]]:
        """Retrieves and clears the prompt message location."""
        if not self.is_connected:
            return None
        try:
            key = self._prompt_msg_key(user_id)
            val = await self._client.get(key)
            if not val:
                return None
            await self._client.delete(key)
            parts = val.split(":", 1)
            if len(parts) == 2 and parts[0].lstrip("-").isdigit() and parts[1].isdigit():
                return int(parts[0]), int(parts[1])
            return None
        except RedisError as e:
            logger.debug(f"Redis error clearing prompt message for user {user_id}: {e}")
            return None
