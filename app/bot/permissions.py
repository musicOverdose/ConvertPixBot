"""Admin capability and permission abstraction."""

from enum import Enum
from app.config import Settings


class AdminCapability(str, Enum):
    """Granular permissions for administrative operations."""
    SUPERADMIN = "*"
    MANAGE_CHANNELS = "channels"
    MANAGE_ACCESS = "access"          # Whitelist and Ban list
    BROADCAST = "broadcast"
    SYSTEM_MAINTENANCE = "maintenance" # Maintenance mode, backups, GC, reload
    VIEW_AUDIT = "audit"


def has_admin_capability(
    user_id: int,
    capability: AdminCapability,
    settings: Settings,
) -> bool:
    """
    Evaluates whether a Telegram user ID possesses a specific capability.
    All configured ADMIN_IDS possess all capabilities (full superadmin).
    Ready for future granular database-backed role assignments.
    """
    if not user_id:
        return False
    # All users in ADMIN_IDS are superadmins with all capabilities
    return settings.is_admin(user_id)
