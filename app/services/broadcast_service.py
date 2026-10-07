"""Resilient Broadcast Engine with FloodWait handling, retry logic, and cooperative cancellation."""

import asyncio
import logging
from typing import Callable, Coroutine, Dict, List, Optional
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from app.database.repository import DatabaseRepository

logger = logging.getLogger(__name__)


class BroadcastService:
    """Manages resilient broadcast dispatching to registered users."""

    def __init__(self, repository: DatabaseRepository):
        self.repository = repository
        self._cancel_events: Dict[int, asyncio.Event] = {}

    def get_cancel_event(self, broadcast_id: int) -> asyncio.Event:
        if broadcast_id not in self._cancel_events:
            self._cancel_events[broadcast_id] = asyncio.Event()
        return self._cancel_events[broadcast_id]

    def cancel_broadcast(self, broadcast_id: int) -> bool:
        """Signals an in-flight broadcast to stop gracefully."""
        if broadcast_id in self._cancel_events:
            self._cancel_events[broadcast_id].set()
            logger.info(f"Cancellation requested for broadcast {broadcast_id}")
            return True
        return False

    async def execute_broadcast(
        self,
        bot: Bot,
        broadcast_id: int,
        source_chat_id: int,
        source_message_id: int,
        target_user_ids: List[int],
        progress_callback: Optional[Callable[[int, int, int, int, int], Coroutine]] = None,
    ) -> dict:
        """
        Executes broadcast loop across target_user_ids.
        Calls progress_callback(processed, total, delivered, blocked, failed) periodically.
        Returns final results dictionary.
        """
        cancel_event = self.get_cancel_event(broadcast_id)
        total = len(target_user_ids)
        delivered = 0
        blocked = 0
        failed = 0
        status = "completed"

        try:
            for idx, user_id in enumerate(target_user_ids, 1):
                # Check for cancellation before dispatch
                if cancel_event.is_set():
                    status = "cancelled"
                    logger.info(f"Broadcast {broadcast_id} cancelled by admin at {idx}/{total}")
                    break

                # Send with automatic FloodWait / RetryAfter handling
                for attempt in range(3):
                    try:
                        await bot.copy_message(
                            chat_id=user_id,
                            from_chat_id=source_chat_id,
                            message_id=source_message_id,
                        )
                        delivered += 1
                        break
                    except TelegramRetryAfter as e:
                        wait_sec = int(e.retry_after) + 1
                        logger.warning(
                            f"FloodWait for user {user_id}. Waiting {wait_sec}s (attempt {attempt+1}/3)..."
                        )
                        await asyncio.sleep(wait_sec)
                    except TelegramForbiddenError:
                        blocked += 1
                        break
                    except TelegramBadRequest as e:
                        failed += 1
                        logger.debug(f"Telegram BadRequest for user {user_id}: {e}")
                        break
                    except Exception as e:
                        logger.debug(f"Transient error sending broadcast to {user_id}: {e}")
                        if attempt == 2:
                            failed += 1
                        await asyncio.sleep(0.5)

                # Rate limiting delay (~30 msg/sec to stay safely within Telegram limits)
                await asyncio.sleep(0.035)

                # Periodic progress notification
                if progress_callback and (idx % 25 == 0 or idx == total or cancel_event.is_set()):
                    try:
                        await progress_callback(idx, total, delivered, blocked, failed)
                    except Exception:
                        pass

                # Periodic database update
                if idx % 50 == 0 or idx == total:
                    await self.repository.update_broadcast_progress(
                        broadcast_id=broadcast_id,
                        delivered=delivered,
                        blocked=blocked,
                        failed=failed,
                        status="running" if status != "cancelled" else "cancelled",
                    )
        finally:
            self._cancel_events.pop(broadcast_id, None)

        # Mark finished in database
        await self.repository.complete_broadcast_record(
            broadcast_id=broadcast_id,
            delivered=delivered,
            blocked=blocked,
            failed=failed,
            status=status,
        )

        return {
            "total": total,
            "delivered": delivered,
            "blocked": blocked,
            "failed": failed,
            "status": status,
        }
