"""Bot startup and uptime tracking service."""

import time

BOT_START_TIME = time.time()


def get_uptime_seconds() -> float:
    return time.time() - BOT_START_TIME


def get_uptime_formatted() -> str:
    elapsed = int(get_uptime_seconds())
    days, rem = divmod(elapsed, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"
