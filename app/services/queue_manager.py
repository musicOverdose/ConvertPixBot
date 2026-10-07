"""Asynchronous worker queue for CPU/IO heavy audio tasks."""

import asyncio
from dataclasses import dataclass, field
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """An item waiting in the worker queue."""
    job_id: str
    user_id: int
    task_func: Callable[..., Coroutine[Any, Any, Any]]
    task_args: tuple = ()
    task_kwargs: dict = field(default_factory=dict)
    future: asyncio.Future = field(default_factory=asyncio.Future)
    enqueued_at: float = field(default_factory=time.time)


class QueueManager:
    """
    Worker pool managing heavy background jobs (downloading, cutting, tagging).
    Enforces MAX_CONCURRENT_JOBS and reports real queue positions to waiting users.
    """

    def __init__(self, max_concurrent_jobs: int = 2):
        self.max_concurrent_jobs = max_concurrent_jobs
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        self._waiting_items: List[QueueItem] = []
        self._active_items: Dict[str, QueueItem] = {}
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self.max_concurrent_jobs):
            worker_task = asyncio.create_task(self._worker_loop(worker_id=i + 1))
            self._workers.append(worker_task)
        logger.info(f"QueueManager started with {self.max_concurrent_jobs} workers.")

    async def stop(self) -> None:
        self._running = False
        for worker_task in self._workers:
            worker_task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("QueueManager stopped.")

    async def _worker_loop(self, worker_id: int) -> None:
        logger.debug(f"Worker {worker_id} started.")
        while self._running:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                break

            async with self._lock:
                if item in self._waiting_items:
                    self._waiting_items.remove(item)
                self._active_items[item.job_id] = item

            try:
                logger.info(f"Worker {worker_id} executing task for job {item.job_id}")
                result = await item.task_func(*item.task_args, **item.task_kwargs)
                if not item.future.done():
                    item.future.set_result(result)
            except Exception as e:
                logger.error(f"Worker {worker_id} error processing job {item.job_id}: {e}", exc_info=True)
                if not item.future.done():
                    item.future.set_exception(e)
            finally:
                async with self._lock:
                    self._active_items.pop(item.job_id, None)
                self._queue.task_done()

    async def enqueue(
        self,
        job_id: str,
        user_id: int,
        task_func: Callable[..., Coroutine[Any, Any, Any]],
        *args,
        **kwargs,
    ) -> tuple[asyncio.Future, int, bool]:
        """
        Add a job to the queue.
        Returns: (Future, queue_position, is_busy).
        If is_busy is True, current active workers are full and position > 0.
        """
        item = QueueItem(
            job_id=job_id,
            user_id=user_id,
            task_func=task_func,
            task_args=args,
            task_kwargs=kwargs,
            future=asyncio.get_running_loop().create_future(),
        )

        async with self._lock:
            self._waiting_items.append(item)
            queue_position = len(self._waiting_items)
            is_busy = len(self._active_items) >= self.max_concurrent_jobs

        await self._queue.put(item)
        return item.future, queue_position, is_busy

    def get_queue_position(self, job_id: str) -> Optional[int]:
        for idx, item in enumerate(self._waiting_items, start=1):
            if item.job_id == job_id:
                return idx
        return None

    @property
    def busy_count(self) -> int:
        return len(self._active_items)

    @property
    def waiting_count(self) -> int:
        return len(self._waiting_items)
