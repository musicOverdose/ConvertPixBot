"""Interactive keyboards for the Telegram Admin Panel."""

from typing import Any, List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings
from app.database.models import BannedUser, RequiredChannel, WhitelistedUser


def get_admin_dashboard_keyboard(maintenance_mode: bool = False) -> InlineKeyboardMarkup:
    """Main administrative dashboard keyboard with dynamic maintenance toggle."""
    maint_label = "🚧 Maint: ON" if maintenance_mode else "🚧 Maint: OFF"
    buttons = [
        [
            InlineKeyboardButton(text="📊 Live Stats", callback_data="adm_stats"),
            InlineKeyboardButton(text="📢 Channels", callback_data="adm_channels"),
        ],
        [
            InlineKeyboardButton(text="⭐ Whitelist", callback_data="adm_whitelist"),
            InlineKeyboardButton(text="🚫 Ban List", callback_data="adm_banlist"),
        ],
        [
            InlineKeyboardButton(text="📣 Broadcast", callback_data="adm_broadcast"),
            InlineKeyboardButton(text="📜 Audit Logs", callback_data="adm_audit:0"),
        ],
        [
            InlineKeyboardButton(text=maint_label, callback_data="adm_maint_toggle"),
            InlineKeyboardButton(text="🧹 GC Cleanup", callback_data="adm_cleanup"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Settings", callback_data="adm_settings"),
            InlineKeyboardButton(text="💬 Messages", callback_data="adm_messages"),
        ],
        [
            InlineKeyboardButton(text="💾 Backup DB", callback_data="adm_backup"),
            InlineKeyboardButton(text="🔄 Reload Config", callback_data="adm_reload"),
        ],
        [
            InlineKeyboardButton(text="❌ Close", callback_data="adm_close"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_channels_keyboard(channels: List[RequiredChannel]) -> InlineKeyboardMarkup:
    """Manage required broadcast channels."""
    buttons = []
    for c in channels:
        display = c.title or (f"@{c.username}" if c.username else c.channel_id)
        if len(display) > 22:
            display = display[:20] + "..."
        status_label = "🟢 On" if c.is_enabled else "🔴 Off"
        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {display}",
                callback_data=f"adm_ch_info:{c.channel_id}",
            ),
            InlineKeyboardButton(
                text=status_label,
                callback_data=f"adm_ch_toggle:{c.channel_id}",
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"adm_ch_del:{c.channel_id}",
            ),
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Add Channel", callback_data="adm_ch_add"),
        InlineKeyboardButton(text="🔄 Sync Info", callback_data="adm_ch_sync"),
    ])
    buttons.append([
        InlineKeyboardButton(text="↩ Back to Admin", callback_data="adm_home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_whitelist_keyboard(whitelist: List[WhitelistedUser]) -> InlineKeyboardMarkup:
    """Manage must-join whitelist users."""
    buttons = []
    for w in whitelist[:15]:  # Show latest 15
        if w.reason:
            label = f"⭐ {w.reason}"
        elif w.username:
            label = f"⭐ @{w.username}"
        else:
            label = f"⭐ ID: {w.user_id}"

        if len(label) > 28:
            label = label[:25] + "..."

        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"adm_wl_info:{w.user_id}"),
            InlineKeyboardButton(text="🗑 Remove", callback_data=f"adm_wl_del:{w.user_id}"),
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Add to Whitelist", callback_data="adm_wl_add"),
        InlineKeyboardButton(text="🔄 Sync Names", callback_data="adm_wl_sync"),
    ])
    buttons.append([
        InlineKeyboardButton(text="↩ Back to Admin", callback_data="adm_home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_banlist_keyboard(banned: List[BannedUser]) -> InlineKeyboardMarkup:
    """Manage banned users."""
    buttons = []
    for b in banned[:15]:  # Show latest 15
        if b.reason:
            label = f"🚫 {b.reason}"
        elif b.username:
            label = f"🚫 @{b.username}"
        else:
            label = f"🚫 ID: {b.user_id}"

        if len(label) > 28:
            label = label[:25] + "..."

        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"adm_ban_info:{b.user_id}"),
            InlineKeyboardButton(text="🔓 Unban", callback_data=f"adm_ban_del:{b.user_id}"),
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Ban User", callback_data="adm_ban_add"),
        InlineKeyboardButton(text="🔄 Sync Info", callback_data="adm_ban_sync"),
    ])
    buttons.append([
        InlineKeyboardButton(text="↩ Back to Admin", callback_data="adm_home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirmation keyboard before dispatching broadcast."""
    buttons = [
        [
            InlineKeyboardButton(text="🚀 Send to All Users", callback_data="adm_bcast_confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="adm_home"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_broadcast_running_keyboard(broadcast_id: int) -> InlineKeyboardMarkup:
    """Active broadcast status keyboard with cancellation button."""
    buttons = [
        [
            InlineKeyboardButton(text="🛑 Cancel Broadcast", callback_data=f"adm_bcast_cancel:{broadcast_id}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_audit_logs_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Paginated navigation for audit logs."""
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"adm_audit:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"Page {page + 1}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="➡️ Next", callback_data=f"adm_audit:{page + 1}"))

    buttons = [
        nav_buttons,
        [InlineKeyboardButton(text="↩ Back to Admin", callback_data="adm_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_back_keyboard(callback_data: str = "adm_home", text: Optional[str] = None) -> InlineKeyboardMarkup:
    """Simple back button to return to admin home or specified menu."""
    btn_text = text if text is not None else ("↩ Back to Admin" if callback_data == "adm_home" else "↩ Back")
    buttons = [
        [InlineKeyboardButton(text=btn_text, callback_data=callback_data)]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_settings_keyboard(settings: Settings, api_mode_manager: Optional[Any] = None) -> InlineKeyboardMarkup:
    """Settings menu keyboard showing API mode, limits, and UX toggles."""
    if api_mode_manager is not None and hasattr(api_mode_manager, "get_configured_mode"):
        is_local = api_mode_manager.get_configured_mode() == "local"
    else:
        is_local = settings.is_local_mode

    mode_btn_text = "☁️ Configure Cloud Mode" if is_local else "🖥️ Configure Local Mode"
    target_mode = "cloud" if is_local else "local"

    tech_icon = "🟢" if settings.show_technical_info else "🔴"
    cover_icon = "🟢" if settings.send_cover_separately else "🔴"

    row1 = [InlineKeyboardButton(text=mode_btn_text, callback_data=f"adm_set_mode:{target_mode}")]
    if is_local:
        row1.append(InlineKeyboardButton(text="✏️ Edit Local URL", callback_data="adm_set_local_url"))

    buttons = [
        row1,
        [
            InlineKeyboardButton(text=f"📦 In: {settings.max_input_mb}MB", callback_data="adm_set_input_mb"),
            InlineKeyboardButton(text=f"📤 Out: {settings.max_output_mb}MB", callback_data="adm_set_output_mb"),
        ],
        [
            InlineKeyboardButton(text=f"{tech_icon} Technical Specs", callback_data="adm_set_toggle:tech"),
            InlineKeyboardButton(text=f"{cover_icon} Separate Cover", callback_data="adm_set_toggle:cover"),
        ],
        [
            InlineKeyboardButton(text="🔄 Reset to .env Defaults", callback_data="adm_set_reset"),
        ],
        [
            InlineKeyboardButton(text="↩ Back to Admin", callback_data="adm_home"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_file_size_preset_keyboard(setting_type: str, is_local: bool) -> InlineKeyboardMarkup:
    """Presets for max input or output file size."""
    if is_local:
        presets = [20, 50, 100, 500, 1000, 2000]
    else:
        presets = [10, 20] if setting_type == "input" else [20, 30, 50]

    rows = []
    current_row = []
    for p in presets:
        current_row.append(
            InlineKeyboardButton(text=f"{p} MB", callback_data=f"adm_set_size:{setting_type}:{p}")
        )
        if len(current_row) == 3:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    rows.append([
        InlineKeyboardButton(text="✏️ Custom Size", callback_data=f"adm_set_size_custom:{setting_type}"),
        InlineKeyboardButton(text="↩ Back to Settings", callback_data="adm_settings"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_messages_keyboard(status_dict: dict) -> InlineKeyboardMarkup:
    """Lists customizable messages with their custom/default status."""
    buttons = []
    for key, info in status_dict.items():
        tag = "⭐ Custom" if info.get("is_custom") else "Default"
        buttons.append([
            InlineKeyboardButton(
                text=f"{info.get('title', key)} ({tag})",
                callback_data=f"adm_msg_view:{key}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="↩ Back to Admin", callback_data="adm_home")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_message_detail_keyboard(msg_key: str, is_custom: bool) -> InlineKeyboardMarkup:
    """Action menu for a specific message (edit, reset, back)."""
    action_row = [
        InlineKeyboardButton(text="✏️ Edit Message", callback_data=f"adm_msg_edit:{msg_key}")
    ]
    if is_custom:
        action_row.append(
            InlineKeyboardButton(text="🔄 Reset to Default", callback_data=f"adm_msg_reset:{msg_key}")
        )
    buttons = [
        action_row,
        [InlineKeyboardButton(text="↩ Back to Messages", callback_data="adm_messages")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

