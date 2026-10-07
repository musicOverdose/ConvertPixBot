"""In-memory sliding-window rate limiter per user."""

from collections import defaultdict, deque
import time
from typing import Tuple


class RateLimiter:
    """Sliding window rate limiter for user actions (e.g. file uploads)."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._user_timestamps = defaultdict(deque)

    def check(self, user_id: int) -> Tuple[bool, int]:
        """
        Check if user_id is within rate limits.
        Returns: (is_allowed, wait_seconds).
        If allowed, records the current timestamp and returns (True, 0).
        If not allowed, returns (False, retry_after_seconds).
        """
        now = time.time()
        timestamps = self._user_timestamps[user_id]

        # Purge timestamps outside the sliding window
        while timestamps and timestamps[0] <= now - self.window_seconds:
            timestamps.popleft()

        if len(timestamps) >= self.max_requests:
            oldest = timestamps[0]
            retry_after = max(1, int(oldest + self.window_seconds - now))
            return False, retry_after

        timestamps.append(now)
        return True, 0

    def reset_user(self, user_id: int) -> None:
        """Reset rate limit history for a specific user."""
        if user_id in self._user_timestamps:
            del self._user_timestamps[user_id]
