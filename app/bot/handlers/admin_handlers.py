"""Interactive Telegram Admin Panel with audit logging, resilient broadcasts, and operational statistics."""

import asyncio
import logging
from typing import List, Optional, Union
from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.database.models import BannedUser, RequiredChannel, WhitelistedUser

from app.bot.keyboards.admin_menu import (
    get_admin_audit_logs_keyboard,
    get_admin_back_keyboard,
    get_admin_banlist_keyboard,
    get_admin_broadcast_confirm_keyboard,
    get_admin_broadcast_running_keyboard,
    get_admin_channels_keyboard,
    get_admin_dashboard_keyboard,
    get_admin_message_detail_keyboard,
    get_admin_messages_keyboard,
    get_admin_settings_keyboard,
    get_admin_whitelist_keyboard,
    get_file_size_preset_keyboard,
)
from app.bot.permissions import AdminCapability, has_admin_capability
from app.bot.states.admin_states import AdminStates
from app.config import Settings, reload_settings
from app.database.repository import DatabaseRepository
from app.services.api_mode_manager import ApiModeManager
from app.services.broadcast_service import BroadcastService
from app.services.job_manager import JobManager
from app.services.message_service import MessageService
from app.services.uptime import get_uptime_formatted

logger = logging.getLogger(__name__)

router = Router(name="admin_handlers_router")


def is_admin_check(event: Union[Message, CallbackQuery], settings: Settings) -> bool:
    """Verifies that the event originates from a configured administrator."""
    user = event.from_user
    if not user:
        return False
    return has_admin_capability(user.id, AdminCapability.SUPERADMIN, settings)


async def render_admin_dashboard(
    settings: Settings,
    repository: Optional[DatabaseRepository] = None,
    job_manager: Optional[JobManager] = None,
) -> tuple[str, any]:
    """Builds the comprehensive operational dashboard text and keyboard."""
    if repository is None:
        from app.database.connection import Database
        repository = DatabaseRepository(Database(settings.db_path))
    if job_manager is None:
        job_manager = JobManager(settings.jobs_dir)

    is_maint = await repository.is_maintenance_mode()
    stats = await repository.get_stats()
    whitelist = await repository.list_whitelist()
    banned = await repository.list_banned()
    channels = await repository.list_channels(enabled_only=True)

    active_jobs_cnt = job_manager.get_active_jobs_count()
    temp_disk_mb = job_manager.get_temp_disk_usage_mb()
    uptime_str = get_uptime_formatted()
    maint_status = "🔴 <b>ACTIVE</b>" if is_maint else "🟢 <b>Normal</b>"
    api_mode_badge = "🖥️ <b>Local Server</b>" if settings.is_local_mode else "☁️ <b>Cloud Mode</b>"

    text = (
        "🎛 <b>SongTaggerBot Admin Dashboard</b>\n\n"
        f"• Status: {maint_status} | Uptime: <code>{uptime_str}</code>\n"
        f"• API Mode: {api_mode_badge} (<code>{settings.effective_api_base_url}</code>)\n"
        f"• Active Users: <b>{stats.unique_users}</b>\n"
        f"• Channels: <b>{len(channels)} active</b>\n"
        f"• Access: <b>{len(whitelist)} whitelisted</b> | <b>{len(banned)} banned</b>\n"
        f"• Active Jobs: <b>{active_jobs_cnt}</b> | Temp Disk: <b>{temp_disk_mb} MB</b>\n"
        f"• Total Processed: <b>{stats.files_processed} files</b> ({stats.total_processed_mb} MB)"
    )
    kb = get_admin_dashboard_keyboard(maintenance_mode=is_maint)
    return text, kb


def render_admin_settings(
    settings: Settings,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> tuple[str, any]:
    """Builds the Bot Configuration & API settings screen text and keyboard."""
    running_mode = api_mode_manager.get_running_mode() if api_mode_manager else settings.telegram_api_mode
    running_endpoint = api_mode_manager.get_running_endpoint() if api_mode_manager else settings.effective_api_base_url
    configured_mode = api_mode_manager.get_configured_mode() if api_mode_manager else ("local" if settings.is_local_mode else "cloud")
    configured_endpoint = api_mode_manager.get_configured_endpoint() if api_mode_manager else settings.effective_api_base_url

    running_badge = "🖥️ <b>Local Server (Centralized)</b>" if running_mode == "local" else "☁️ <b>Cloud (api.telegram.org)</b>"
    tech_badge = "🟢 Enabled" if settings.show_technical_info else "🔴 Disabled"
    cover_badge = "🟢 Enabled" if settings.send_cover_separately else "🔴 Disabled"

    notice_section = ""
    if api_mode_manager and api_mode_manager.is_migration_required():
        notice_section = (
            "\n\n⚠️ <b>Telegram Bot API Migration Required!</b>\n"
            f"• <b>Current Server:</b> <code>{running_endpoint}</code>\n"
            f"• <b>Target Server:</b> <code>{configured_endpoint}</code>\n\n"
            "<i>Before restarting container:</i>\n"
            "1. Stop the bot container.\n"
            "2. Call Telegram <code>logOut</code> through the current/old server.\n"
            "3. Start the bot with the new endpoint."
        )
    elif api_mode_manager and api_mode_manager.is_restart_required():
        notice_section = (
            "\n\n⚠️ <b>Restart Required to Apply API Mode!</b>\n"
            f"• <b>Configured for next start:</b> <b>{configured_mode.upper()}</b> (<code>{configured_endpoint}</code>)\n"
            "<i>Please restart the container to apply configuration.</i>"
        )

    text = (
        "⚙️ <b>Bot Configuration & API Settings</b>\n\n"
        f"• <b>Active API Mode:</b> {running_badge}\n"
        f"• <b>Active Endpoint:</b> <code>{running_endpoint}</code>\n"
        f"• <b>Configured Mode:</b> <b>{configured_mode.upper()}</b>\n"
        f"• <b>Configured Endpoint:</b> <code>{configured_endpoint}</code>\n"
        f"• <b>Max File Input:</b> <b>{settings.max_input_mb} MB</b>\n"
        f"• <b>Max File Output:</b> <b>{settings.max_output_mb} MB</b>\n"
        f"• <b>Rate Limit:</b> <b>{settings.rate_limit_uploads_per_minute} uploads/min</b>\n"
        f"• <b>Concurrency:</b> <b>{settings.max_user_concurrent_jobs}/user</b> | <b>{settings.max_global_concurrent_jobs} global</b>\n"
        f"• <b>Technical Specs in Preview:</b> {tech_badge}\n"
        f"• <b>Send Cover Separately:</b> {cover_badge}"
        f"{notice_section}\n\n"
        "<i>Use buttons below to configure API modes, update limits, or toggle UX options.</i>"
    )
    kb = get_admin_settings_keyboard(settings, api_mode_manager=api_mode_manager)
    return text, kb


# --- Dashboard Entry Points ---

@router.message(Command("admin"))
async def cmd_admin(
    message: Message,
    state: FSMContext,
    settings: Settings,
    repository: Optional[DatabaseRepository] = None,
    job_manager: Optional[JobManager] = None,
) -> None:
    if not is_admin_check(message, settings):
        return
    await state.clear()
    text, kb = await render_admin_dashboard(settings, repository, job_manager)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_home")
async def callback_admin_home(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    repository: Optional[DatabaseRepository] = None,
    job_manager: Optional[JobManager] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    await state.clear()
    text, kb = await render_admin_dashboard(settings, repository, job_manager)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "adm_close")
async def callback_admin_close(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    await state.clear()
    if callback.message:
        await callback.message.delete()
    await callback.answer()


# --- Maintenance Mode Toggle ---

@router.callback_query(F.data == "adm_maint_toggle")
async def callback_adm_maint_toggle(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    job_manager: JobManager,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    current = await repository.is_maintenance_mode()
    new_state = not current
    await repository.set_maintenance_mode(new_state)
    job_manager.set_maintenance_mode(new_state)

    admin_id = callback.from_user.id
    await repository.log_audit_action(
        admin_id=admin_id,
        action="maintenance_mode",
        details="Enabled" if new_state else "Disabled",
    )
    status_label = "ENABLED (New user uploads paused)" if new_state else "DISABLED (Normal operations)"
    await callback.answer(f"Maintenance mode: {status_label}", show_alert=True)

    text, kb = await render_admin_dashboard(settings, repository, job_manager)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# --- Live Statistics ---

@router.message(Command("stats"))
async def cmd_stats(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    stats = await repository.get_stats()
    text = (
        "📊 <b>SongTaggerBot Operational Statistics</b>\n\n"
        f"• Uptime: <code>{get_uptime_formatted()}</code>\n"
        f"• Files Received: <b>{stats.files_received}</b>\n"
        f"• Files Processed: <b>{stats.files_processed}</b>\n"
        f"• Files Failed: <b>{stats.files_failed}</b>\n"
        f"• Cuts Performed: <b>{stats.cuts_performed}</b>\n"
        f"• Covers Updated: <b>{stats.covers_updated}</b>\n"
        f"• Lyrics Updated: <b>{stats.lyrics_updated}</b>\n"
        f"• Active Users: <b>{stats.unique_users}</b>\n"
        f"• Total Data Processed: <b>{stats.total_processed_mb} MB</b>"
    )
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "adm_stats")
async def callback_adm_stats(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    stats = await repository.get_stats()
    text = (
        "📊 <b>SongTaggerBot Operational Statistics</b>\n\n"
        f"• Uptime: <code>{get_uptime_formatted()}</code>\n"
        f"• Files Received: <b>{stats.files_received}</b>\n"
        f"• Files Processed: <b>{stats.files_processed}</b>\n"
        f"• Files Failed: <b>{stats.files_failed}</b>\n"
        f"• Cuts Performed: <b>{stats.cuts_performed}</b>\n"
        f"• Covers Updated: <b>{stats.covers_updated}</b>\n"
        f"• Lyrics Updated: <b>{stats.lyrics_updated}</b>\n"
        f"• Active Users: <b>{stats.unique_users}</b>\n"
        f"• Total Data Processed: <b>{stats.total_processed_mb} MB</b>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


# --- Configuration Reload, Cleanup & Backups ---

@router.message(Command("reloadconfig"))
async def cmd_reload_config(
    message: Message,
    settings: Settings,
    repository: Optional[DatabaseRepository] = None,
) -> None:
    if not is_admin_check(message, settings):
        return
    new_settings = reload_settings()
    if repository:
        await repository.log_audit_action(
            admin_id=message.from_user.id,
            action="reload_config",
            details="Environment reloaded",
        )
    await message.answer(
        f"🔄 <b>Configuration reloaded!</b>\n\n"
        f"• Max Input: {new_settings.max_input_mb} MB\n"
        f"• Max Output: {new_settings.max_output_mb} MB\n"
        f"• Max Workers: {new_settings.max_concurrent_jobs}\n"
        f"• Rate Limit: {new_settings.rate_limit_uploads_per_minute}/min\n"
        f"• Admins: {len(new_settings.admin_ids)}",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adm_reload")
async def callback_adm_reload(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    new_settings = reload_settings()
    await repository.log_audit_action(
        admin_id=callback.from_user.id,
        action="reload_config",
        details="Environment reloaded via admin panel",
    )
    await callback.answer("Configuration reloaded from environment!", show_alert=True)
    if callback.message:
        text = (
            "🔄 <b>Configuration reloaded!</b>\n\n"
            f"• Max Input: {new_settings.max_input_mb} MB\n"
            f"• Max Output: {new_settings.max_output_mb} MB\n"
            f"• Max Workers: {new_settings.max_concurrent_jobs}\n"
            f"• Rate Limit: {new_settings.rate_limit_uploads_per_minute}/min\n"
            f"• Admins: {len(new_settings.admin_ids)}"
        )
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "adm_cleanup")
async def callback_adm_cleanup(
    callback: CallbackQuery, settings: Settings, job_manager: JobManager, repository: DatabaseRepository
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    cleaned_expired = job_manager.cleanup_expired_jobs()
    cleaned_orphaned = job_manager.cleanup_orphaned_job_dirs()
    total_cleaned = cleaned_expired + cleaned_orphaned

    await repository.log_audit_action(
        admin_id=callback.from_user.id,
        action="gc_cleanup",
        details=f"Cleaned {total_cleaned} directories",
    )

    text = (
        f"🧹 <b>Garbage Collection Complete</b>\n\n"
        f"• Expired jobs cleaned: <b>{cleaned_expired}</b>\n"
        f"• Orphaned directories swept: <b>{cleaned_orphaned}</b>\n"
        f"• Remaining temp storage: <b>{job_manager.get_temp_disk_usage_mb()} MB</b>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "adm_backup")
async def callback_adm_backup(
    callback: CallbackQuery, settings: Settings, repository: DatabaseRepository
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    try:
        backup_path = await repository.backup_database(
            backup_dir=settings.backups_dir,
            retention_days=settings.backup_retention_days,
        )
        file_size_kb = round(backup_path.stat().st_size / 1024, 1)
        await repository.log_audit_action(
            admin_id=callback.from_user.id,
            action="backup_database",
            target=str(backup_path.name),
            details=f"Size: {file_size_kb} KB",
        )
        text = (
            "💾 <b>Database Online Backup Complete!</b>\n\n"
            f"• File: <code>{backup_path.name}</code>\n"
            f"• Size: <b>{file_size_kb} KB</b>\n"
            f"• Retention: <b>{settings.backup_retention_days} days</b>"
        )
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        text = f"❌ <b>Backup failed:</b> {e}"

    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


# --- Admin Audit Logs View ---

@router.callback_query(F.data.startswith("adm_audit:"))
async def callback_adm_audit(
    callback: CallbackQuery, settings: Settings, repository: DatabaseRepository
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    page_str = callback.data.split(":", 1)[1]
    page = int(page_str) if page_str.isdigit() else 0
    limit = 7
    offset = page * limit

    logs, total_count = await repository.get_audit_logs(limit=limit, offset=offset)
    total_pages = max(1, (total_count + limit - 1) // limit)

    if not logs:
        text = "📜 <b>Admin Audit Trail</b>\n\nNo administrative actions recorded yet."
    else:
        lines = [f"📜 <b>Admin Audit Trail</b> (Page {page + 1}/{total_pages})\n"]
        for log in logs:
            target_str = f" &rarr; <code>{log.target}</code>" if log.target else ""
            details_str = f" | {log.details}" if log.details else ""
            ts_short = log.created_at[:19].replace("T", " ")
            lines.append(
                f"• <b>{log.action}</b> by <code>{log.admin_id}</code>{target_str}{details_str}\n"
                f"  <i>{ts_short}</i>"
            )
        text = "\n".join(lines)

    kb = get_admin_audit_logs_keyboard(page=page, total_pages=total_pages)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- Must-Join Channels Management ---

@router.message(Command("channels"))
async def cmd_channels(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    channels = await repository.list_channels()
    if not channels:
        await message.answer("📢 No required channels configured.")
        return
    lines = ["📢 <b>Required Channels:</b>\n"]
    for c in channels:
        status_emoji = "🟢 Enabled" if c.is_enabled else "🔴 Disabled"
        display = c.username or c.channel_id
        lines.append(f"• <b>{display}</b> ({status_emoji}) - ID: <code>{c.channel_id}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


# --- Required Broadcast Channels Management ---

def _safe_alert(text: str, max_len: int = 195) -> str:
    """Safely truncates alert text to strictly stay within Telegram's 200-char answerCallbackQuery limit."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _render_channels_text(channels: List[RequiredChannel]) -> str:
    lines = [
        "📢 <b>Must-Join Channels Management</b>\n",
        "Users are required to join these channels before they can use the bot.\n"
        "Ensure the bot is added as an <b>Administrator</b> in every channel.\n",
    ]
    if channels:
        lines.append("<b>Configured Channels:</b>")
        for c in channels:
            title_display = f"<b>{c.title}</b>" if c.title else f"<b>{c.channel_id}</b>"
            user_part = f"@{c.username} • " if c.username else ""
            status_badge = "🟢 <b>Active</b>" if c.is_enabled else "🔴 <b>Disabled</b>"
            lines.append(f"• {title_display} ({user_part}<code>{c.channel_id}</code>) — {status_badge}")
        active_cnt = sum(1 for c in channels if c.is_enabled)
        lines.append(f"\nTotal channels: <b>{len(channels)}</b> (<b>{active_cnt}</b> active)")
    else:
        lines.append("<i>No required channels configured. Must-join is currently bypassed.</i>")
    return "\n".join(lines)


async def _resolve_and_add_channel(
    bot, repository: DatabaseRepository, channel_input: str
) -> tuple[bool, str, Optional[str], Optional[str], Optional[str], bool]:
    """Resolves Telegram channel metadata and stores in database."""
    target_id = channel_input.strip()
    if target_id.startswith("https://t.me/"):
        target_id = "@" + target_id.split("https://t.me/")[1].split("/")[0].lstrip("+")

    chat = None
    is_bot_admin = False
    try:
        chat_arg = int(target_id) if (target_id.startswith("-") or target_id.isdigit()) else target_id
        chat = await bot.get_chat(chat_arg)
    except Exception as e:
        logger.debug(f"Could not get chat info directly for {target_id}: {e}")

    channel_id = str(chat.id) if chat else target_id
    username = chat.username if chat and chat.username else (target_id.lstrip("@") if target_id.startswith("@") else None)
    title = chat.title if chat and chat.title else (f"@{username}" if username else channel_id)
    invite_link = None

    if chat:
        invite_link = chat.invite_link
        if not invite_link and chat.username:
            invite_link = f"https://t.me/{chat.username}"

        try:
            member = await bot.get_chat_member(chat_id=chat.id, user_id=bot.id)
            is_bot_admin = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
            if is_bot_admin and not invite_link:
                try:
                    invite_link = await bot.export_chat_invite_link(chat.id)
                except Exception:
                    pass
        except Exception:
            is_bot_admin = False

    success = await repository.add_channel(
        channel_id=channel_id,
        username=username,
        title=title,
        invite_link=invite_link,
    )
    return success, channel_id, username, title, invite_link, is_bot_admin


@router.callback_query(F.data == "adm_channels")
async def callback_adm_channels(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    channels = await repository.list_channels()
    text = _render_channels_text(channels)
    kb = get_admin_channels_keyboard(channels)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_ch_info:"))
async def callback_adm_ch_info(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    channel_id = callback.data.split(":", 1)[1]
    channels = await repository.list_channels()
    target = next((c for c in channels if c.channel_id == channel_id), None)
    if not target:
        await callback.answer("Channel not found.", show_alert=True)
        return

    bot_status = "Unknown"
    try:
        chat_arg = int(target.channel_id) if (target.channel_id.startswith("-") or target.channel_id.isdigit()) else (f"@{target.username}" if target.username else target.channel_id)
        member = await callback.bot.get_chat_member(chat_id=chat_arg, user_id=callback.bot.id)
        if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            bot_status = "🟢 Admin"
        else:
            bot_status = f"🔴 {member.status.capitalize()}"
    except Exception:
        bot_status = "⚠️ No access"

    title_str = target.title or target.channel_id
    if len(title_str) > 24:
        title_str = title_str[:21] + "..."
    user_str = f"@{target.username}" if target.username else "Private"
    status_str = "🟢 On" if target.is_enabled else "🔴 Off"
    link_str = target.invite_link or "None"
    if len(link_str) > 30:
        link_str = link_str[:27] + "..."

    info_text = (
        f"📢 {title_str}\n"
        f"• ID: {target.channel_id}\n"
        f"• User: {user_str}\n"
        f"• Status: {status_str} | Bot: {bot_status}\n"
        f"• Link: {link_str}"
    )
    await callback.answer(_safe_alert(info_text), show_alert=True)


@router.callback_query(F.data == "adm_ch_sync")
async def callback_adm_ch_sync(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    channels = await repository.list_channels()
    synced_count = 0
    for c in channels:
        try:
            chat_arg = int(c.channel_id) if (c.channel_id.startswith("-") or c.channel_id.isdigit()) else (f"@{c.username}" if c.username else c.channel_id)
            chat = await callback.bot.get_chat(chat_arg)
            if chat:
                invite_link = c.invite_link or chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
                await repository.add_channel(
                    channel_id=c.channel_id,
                    username=chat.username or c.username,
                    title=chat.title or c.title,
                    invite_link=invite_link,
                )
                synced_count += 1
        except Exception:
            pass

    channels = await repository.list_channels()
    text = _render_channels_text(channels)
    kb = get_admin_channels_keyboard(channels)
    await callback.answer(f"✅ Synced {synced_count}/{len(channels)} channels from Telegram!", show_alert=True)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_ch_toggle:"))
async def callback_adm_ch_toggle(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    channel_id = callback.data.split(":", 1)[1]
    channels = await repository.list_channels()
    target = next((c for c in channels if c.channel_id == channel_id), None)
    if target:
        new_state = not target.is_enabled
        await repository.set_channel_enabled(channel_id, new_state)
        await repository.log_audit_action(
            admin_id=callback.from_user.id,
            action="toggle_channel",
            target=channel_id,
            details="Enabled" if new_state else "Disabled",
        )
        await callback.answer(f"Channel {'enabled' if new_state else 'disabled'}.")
    channels = await repository.list_channels()
    text = _render_channels_text(channels)
    kb = get_admin_channels_keyboard(channels)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_ch_del:"))
async def callback_adm_ch_del(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    channel_id = callback.data.split(":", 1)[1]
    await repository.remove_channel(channel_id)
    await repository.log_audit_action(
        admin_id=callback.from_user.id,
        action="remove_channel",
        target=channel_id,
    )
    await callback.answer(f"Channel {channel_id} deleted.")
    channels = await repository.list_channels()
    text = _render_channels_text(channels)
    kb = get_admin_channels_keyboard(channels)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_ch_add")
async def callback_adm_ch_add(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_channel_input)
    text = (
        "📢 <b>Add Required Channel</b>\n\n"
        "Send the channel's <b>@username</b> or numeric ID (e.g. <code>-1001234567890</code>):\n"
        "<code>@MyMusicChannel</code>\n\n"
        "💡 <i>Tip: Make sure the bot is already an Administrator in the channel. The bot will automatically fetch the channel's title and invite link!</i>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_channel_input)
async def process_channel_input(
    message: Message, state: FSMContext, settings: Settings, repository: DatabaseRepository
) -> None:
    if not is_admin_check(message, settings):
        return
    channel_input = message.text.strip() if message.text else ""
    if not channel_input:
        await message.reply("Please provide a valid channel identifier.")
        return

    success, channel_id, username, title, invite_link, is_bot_admin = await _resolve_and_add_channel(
        bot=message.bot, repository=repository, channel_input=channel_input
    )
    await state.clear()

    if success:
        await repository.log_audit_action(
            admin_id=message.from_user.id,
            action="add_channel",
            target=channel_id,
            details=f"Title: {title}",
        )
        channels = await repository.list_channels()
        kb = get_admin_channels_keyboard(channels)
        admin_warning = (
            "\n🤖 <b>Bot Status:</b> 🟢 Administrator (Active & Ready)"
            if is_bot_admin
            else "\n🤖 <b>Bot Status:</b> ⚠️ <b>Not Admin yet</b>\n<i>Please promote the bot to Administrator so it can check memberships!</i>"
        )
        await message.answer(
            f"✅ <b>Channel Added Successfully!</b>\n\n"
            f"📢 <b>Title:</b> {title}\n"
            f"🆔 <b>ID:</b> <code>{channel_id}</code>\n"
            f"👤 <b>Username:</b> {f'@{username}' if username else '<i>(Private)</i>'}\n"
            f"🔗 <b>Link:</b> {invite_link or '<i>(None)</i>'}"
            f"{admin_warning}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"❌ Failed to add channel: <b>{channel_input}</b>",
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )


@router.message(Command("addchannel"))
async def cmd_add_channel(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: <code>/addchannel @username</code> or <code>/addchannel -100123456789</code>", parse_mode="HTML")
        return
    channel_input = parts[1].strip()
    success, channel_id, username, title, invite_link, is_bot_admin = await _resolve_and_add_channel(
        bot=message.bot, repository=repository, channel_input=channel_input
    )
    if success:
        await repository.log_audit_action(
            admin_id=message.from_user.id,
            action="add_channel",
            target=channel_id,
            details=f"Title: {title}",
        )
        admin_warning = (
            "\n🤖 <b>Bot Status:</b> 🟢 Administrator (Active)"
            if is_bot_admin
            else "\n🤖 <b>Bot Status:</b> ⚠️ <b>Not Admin yet</b> (Promote bot to admin in channel)"
        )
        await message.answer(
            f"✅ Added channel: <b>{title}</b> (<code>{channel_id}</code>){admin_warning}",
            parse_mode="HTML",
        )
    else:
        await message.answer(f"❌ Failed to add channel: <b>{channel_input}</b>", parse_mode="HTML")


@router.message(Command("delchannel"))
async def cmd_del_channel(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: <code>/delchannel @username</code> or <code>/delchannel -100123456789</code>", parse_mode="HTML")
        return
    channel_input = parts[1].strip()
    success = await repository.remove_channel(channel_input)
    if success:
        await repository.log_audit_action(
            admin_id=message.from_user.id,
            action="remove_channel",
            target=channel_input,
        )
        await message.answer(f"✅ Removed channel: <b>{channel_input}</b>", parse_mode="HTML")
    else:
        await message.answer(f"❌ Channel not found: <b>{channel_input}</b>", parse_mode="HTML")


@router.message(Command("channels"))
async def cmd_channels(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    channels = await repository.list_channels()
    text = _render_channels_text(channels)
    kb = get_admin_channels_keyboard(channels)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# --- Whitelist Management ---

def _render_whitelist_text(whitelist: List[WhitelistedUser]) -> str:
    lines = [
        "⭐ <b>Must-Join Whitelist</b>\n",
        "Users on this list bypass mandatory channel membership checks.\n",
    ]
    if whitelist:
        lines.append("<b>Whitelisted Users:</b>")
        for w in whitelist[:15]:
            if w.reason and w.username:
                lines.append(f"• <b>{w.reason}</b> (@{w.username} • <code>{w.user_id}</code>)")
            elif w.reason:
                lines.append(f"• <b>{w.reason}</b> (<code>{w.user_id}</code>)")
            elif w.username:
                lines.append(f"• @{w.username} (<code>{w.user_id}</code>)")
            else:
                lines.append(f"• <code>{w.user_id}</code>")
        if len(whitelist) > 15:
            lines.append(f"<i>...and {len(whitelist) - 15} more</i>")
        lines.append(f"\nTotal: <b>{len(whitelist)}</b>")
    else:
        lines.append("<i>No users in whitelist.</i>")
    return "\n".join(lines)


def _render_banlist_text(banned: List[BannedUser]) -> str:
    lines = [
        "🚫 <b>Banned Users Management</b>\n",
        "Banned users are blocked from all bot functionalities at middleware level.\n",
    ]
    if banned:
        lines.append("<b>Banned Users:</b>")
        for b in banned[:15]:
            if b.reason and b.username:
                lines.append(f"• <b>{b.reason}</b> (@{b.username} • <code>{b.user_id}</code>)")
            elif b.reason:
                lines.append(f"• <b>{b.reason}</b> (<code>{b.user_id}</code>)")
            elif b.username:
                lines.append(f"• @{b.username} (<code>{b.user_id}</code>)")
            else:
                lines.append(f"• <code>{b.user_id}</code>")
        if len(banned) > 15:
            lines.append(f"<i>...and {len(banned) - 15} more</i>")
        lines.append(f"\nTotal: <b>{len(banned)}</b>")
    else:
        lines.append("<i>No users currently banned.</i>")
    return "\n".join(lines)


@router.callback_query(F.data == "adm_whitelist")
async def callback_adm_whitelist(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    whitelist = await repository.list_whitelist()
    text = _render_whitelist_text(whitelist)
    kb = get_admin_whitelist_keyboard(whitelist)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_wl_info:"))
async def callback_adm_wl_info(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    user_id_str = callback.data.split(":", 1)[1]
    try:
        user_id = int(user_id_str)
        whitelist = await repository.list_whitelist()
        entry = next((w for w in whitelist if w.user_id == user_id), None)
        if entry:
            title_str = entry.reason or "(No title set)"
            if len(title_str) > 30:
                title_str = title_str[:27] + "..."
            username_str = f"@{entry.username}" if entry.username else "(None)"
            added_str = entry.added_at[:10] if entry.added_at else "Unknown"
            info_text = (
                f"⭐ Whitelist User\n"
                f"• Title: {title_str}\n"
                f"• ID: {entry.user_id}\n"
                f"• User: {username_str}\n"
                f"• Added: {added_str}"
            )
            await callback.answer(_safe_alert(info_text), show_alert=True)
        else:
            await callback.answer("User not found in whitelist.", show_alert=True)
    except Exception:
        await callback.answer("Error retrieving user info.", show_alert=True)


@router.callback_query(F.data.startswith("adm_wl_del:"))
async def callback_adm_wl_del(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    user_id_str = callback.data.split(":", 1)[1]
    try:
        user_id = int(user_id_str)
        await repository.remove_from_whitelist(user_id)
        await repository.log_audit_action(
            admin_id=callback.from_user.id,
            action="remove_whitelist",
            target=str(user_id),
        )
        await callback.answer(f"Removed user {user_id} from whitelist.")
    except ValueError:
        await callback.answer("Invalid user ID.")
    whitelist = await repository.list_whitelist()
    text = _render_whitelist_text(whitelist)
    kb = get_admin_whitelist_keyboard(whitelist)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_wl_sync")
async def callback_adm_wl_sync(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    whitelist = await repository.list_whitelist()
    synced_count = 0
    for w in whitelist:
        try:
            chat = await callback.bot.get_chat(w.user_id)
            if chat:
                username = chat.username or w.username
                reason = w.reason or chat.full_name
                await repository.add_to_whitelist(
                    user_id=w.user_id,
                    username=username,
                    reason=reason,
                )
                synced_count += 1
        except Exception:
            pass

    whitelist = await repository.list_whitelist()
    text = _render_whitelist_text(whitelist)
    kb = get_admin_whitelist_keyboard(whitelist)
    await callback.answer(f"✅ Synced {synced_count}/{len(whitelist)} whitelisted users!", show_alert=True)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_wl_add")
async def callback_adm_wl_add(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_whitelist_input)
    text = (
        "⭐ <b>Add User to Whitelist</b>\n\n"
        "Send the Telegram user ID followed by a title/name for this user:\n"
        "<code>123456789 Alex (VIP Producer)</code>\n\n"
        "💡 <i>The title will be shown on the menu buttons so you can easily recognize them. "
        "If you only send the ID, we will try to fetch their Telegram name automatically!</i>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_whitelist_input)
async def process_whitelist_input(
    message: Message, state: FSMContext, settings: Settings, repository: DatabaseRepository
) -> None:
    if not is_admin_check(message, settings):
        return
    text = message.text.strip() if message.text else ""
    parts = text.split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        await message.reply("⚠️ Please enter a numeric Telegram user ID (e.g. <code>123456789 Alex</code>).", parse_mode="HTML")
        return
    user_id = int(parts[0])
    reason = parts[1].strip() if len(parts) > 1 else None

    username = None
    try:
        chat_info = await message.bot.get_chat(user_id)
        if chat_info:
            username = chat_info.username
            if not reason:
                reason = chat_info.full_name or (f"@{chat_info.username}" if chat_info.username else None)
    except Exception:
        pass

    await repository.add_to_whitelist(user_id=user_id, username=username, reason=reason)
    await repository.log_audit_action(
        admin_id=message.from_user.id,
        action="add_whitelist",
        target=str(user_id),
        details=reason,
    )
    await state.clear()
    whitelist = await repository.list_whitelist()
    kb = get_admin_whitelist_keyboard(whitelist)
    title_disp = f" (<b>{reason}</b>)" if reason else ""
    await message.answer(f"✅ Added user <code>{user_id}</code>{title_disp} to whitelist.", reply_markup=kb, parse_mode="HTML")


@router.message(Command("whitelist"))
async def cmd_whitelist(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) >= 2 and parts[1].lower() == "add":
        if len(parts) < 3 or not parts[2].split()[0].isdigit():
            await message.answer("Usage: <code>/whitelist add &lt;user_id&gt; [title/name]</code>", parse_mode="HTML")
            return
        sub = parts[2].split(maxsplit=1)
        uid = int(sub[0])
        reason = sub[1].strip() if len(sub) > 1 else None

        username = None
        try:
            chat_info = await message.bot.get_chat(uid)
            if chat_info:
                username = chat_info.username
                if not reason:
                    reason = chat_info.full_name or (f"@{chat_info.username}" if chat_info.username else None)
        except Exception:
            pass

        await repository.add_to_whitelist(uid, username=username, reason=reason)
        await repository.log_audit_action(
            admin_id=message.from_user.id,
            action="add_whitelist",
            target=str(uid),
            details=reason,
        )
        title_disp = f" (<b>{reason}</b>)" if reason else ""
        await message.answer(f"✅ User <code>{uid}</code>{title_disp} whitelisted.", parse_mode="HTML")
    elif len(parts) >= 2 and parts[1].lower() in ("del", "remove"):
        if len(parts) < 3 or not parts[2].strip().isdigit():
            await message.answer("Usage: <code>/whitelist del &lt;user_id&gt;</code>", parse_mode="HTML")
            return
        uid = int(parts[2].strip())
        await repository.remove_from_whitelist(uid)
        await repository.log_audit_action(
            admin_id=message.from_user.id,
            action="remove_whitelist",
            target=str(uid),
        )
        await message.answer(f"✅ User <code>{uid}</code> removed from whitelist.", parse_mode="HTML")
    else:
        whitelist = await repository.list_whitelist()
        if not whitelist:
            await message.answer("⭐ Whitelist is empty.")
            return
        lines = ["⭐ <b>Whitelisted Users:</b>\n"]
        for w in whitelist:
            if w.reason and w.username:
                lines.append(f"• <b>{w.reason}</b> (@{w.username} • <code>{w.user_id}</code>)")
            elif w.reason:
                lines.append(f"• <b>{w.reason}</b> — <code>{w.user_id}</code>")
            elif w.username:
                lines.append(f"• @{w.username} — <code>{w.user_id}</code>")
            else:
                lines.append(f"• <code>{w.user_id}</code>")
        await message.answer("\n".join(lines), parse_mode="HTML")


# --- Ban List Management ---

@router.callback_query(F.data == "adm_banlist")
async def callback_adm_banlist(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    banned = await repository.list_banned()
    text = _render_banlist_text(banned)
    kb = get_admin_banlist_keyboard(banned)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_ban_info:"))
async def callback_adm_ban_info(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    user_id_str = callback.data.split(":", 1)[1]
    try:
        user_id = int(user_id_str)
        banned = await repository.list_banned()
        entry = next((b for b in banned if b.user_id == user_id), None)
        if entry:
            reason_str = entry.reason or "(No reason specified)"
            if len(reason_str) > 35:
                reason_str = reason_str[:32] + "..."
            username_str = f"@{entry.username}" if entry.username else "(None)"
            banned_str = entry.banned_at[:10] if entry.banned_at else "Unknown"
            info_text = (
                f"🚫 Banned User\n"
                f"• Reason: {reason_str}\n"
                f"• ID: {entry.user_id}\n"
                f"• User: {username_str}\n"
                f"• Banned: {banned_str}"
            )
            await callback.answer(_safe_alert(info_text), show_alert=True)
        else:
            await callback.answer("User not found in ban list.", show_alert=True)
    except Exception:
        await callback.answer("Error retrieving user info.", show_alert=True)


@router.callback_query(F.data.startswith("adm_ban_del:"))
async def callback_adm_ban_del(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    user_id_str = callback.data.split(":", 1)[1]
    try:
        user_id = int(user_id_str)
        await repository.unban_user(user_id)
        await repository.log_audit_action(
            admin_id=callback.from_user.id,
            action="unban_user",
            target=str(user_id),
        )
        await callback.answer(f"Unbanned user {user_id}.")
    except ValueError:
        await callback.answer("Invalid user ID.")
    banned = await repository.list_banned()
    text = _render_banlist_text(banned)
    kb = get_admin_banlist_keyboard(banned)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_ban_sync")
async def callback_adm_ban_sync(callback: CallbackQuery, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    banned = await repository.list_banned()
    synced_count = 0
    for b in banned:
        try:
            chat = await callback.bot.get_chat(b.user_id)
            if chat:
                username = chat.username or b.username
                await repository.ban_user(
                    user_id=b.user_id,
                    username=username,
                    reason=b.reason,
                )
                synced_count += 1
        except Exception:
            pass

    banned = await repository.list_banned()
    text = _render_banlist_text(banned)
    kb = get_admin_banlist_keyboard(banned)
    await callback.answer(f"✅ Synced {synced_count}/{len(banned)} banned users!", show_alert=True)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_ban_add")
async def callback_adm_ban_add(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_ban_input)
    text = (
        "🚫 <b>Ban User</b>\n\n"
        "Send the Telegram user ID to ban, optionally followed by a reason:\n"
        "<code>123456789 spamming large files</code>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_ban_input)
async def process_ban_input(
    message: Message, state: FSMContext, settings: Settings, repository: DatabaseRepository
) -> None:
    if not is_admin_check(message, settings):
        return
    text = message.text.strip() if message.text else ""
    parts = text.split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        await message.reply("⚠️ Please enter a numeric Telegram user ID (e.g. <code>123456789 spammer</code>).", parse_mode="HTML")
        return
    user_id = int(parts[0])
    reason = parts[1].strip() if len(parts) > 1 else None

    username = None
    try:
        chat_info = await message.bot.get_chat(user_id)
        if chat_info:
            username = chat_info.username
    except Exception:
        pass

    await repository.ban_user(user_id=user_id, username=username, reason=reason)
    await repository.log_audit_action(
        admin_id=message.from_user.id,
        action="ban_user",
        target=str(user_id),
        details=reason,
    )
    await state.clear()
    banned = await repository.list_banned()
    kb = get_admin_banlist_keyboard(banned)
    reason_disp = f" (<b>{reason}</b>)" if reason else ""
    await message.answer(f"🚫 User <code>{user_id}</code>{reason_disp} has been banned.", reply_markup=kb, parse_mode="HTML")


@router.message(Command("ban"))
async def cmd_ban(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/ban &lt;user_id&gt; [reason]</code>", parse_mode="HTML")
        return
    uid = int(parts[1])
    reason = parts[2].strip() if len(parts) > 2 else None

    username = None
    try:
        chat_info = await message.bot.get_chat(uid)
        if chat_info:
            username = chat_info.username
    except Exception:
        pass

    await repository.ban_user(uid, username=username, reason=reason)
    await repository.log_audit_action(
        admin_id=message.from_user.id,
        action="ban_user",
        target=str(uid),
        details=reason,
    )
    reason_disp = f" (<b>{reason}</b>)" if reason else ""
    await message.answer(f"🚫 User <code>{uid}</code>{reason_disp} has been banned.", parse_mode="HTML")


@router.message(Command("unban"))
async def cmd_unban(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer("Usage: <code>/unban &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    uid = int(parts[1].strip())
    await repository.unban_user(uid)
    await repository.log_audit_action(
        admin_id=message.from_user.id,
        action="unban_user",
        target=str(uid),
    )
    await message.answer(f"✅ User <code>{uid}</code> has been unbanned.", parse_mode="HTML")


@router.message(Command("banlist"))
async def cmd_banlist(message: Message, settings: Settings, repository: DatabaseRepository) -> None:
    if not is_admin_check(message, settings):
        return
    banned = await repository.list_banned()
    if not banned:
        await message.answer("🚫 Ban list is empty.")
        return
    lines = ["🚫 <b>Banned Users:</b>\n"]
    for b in banned:
        if b.reason and b.username:
            lines.append(f"• <b>{b.reason}</b> (@{b.username} • <code>{b.user_id}</code>)")
        elif b.reason:
            lines.append(f"• <b>{b.reason}</b> — <code>{b.user_id}</code>")
        elif b.username:
            lines.append(f"• @{b.username} — <code>{b.user_id}</code>")
        else:
            lines.append(f"• <code>{b.user_id}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


# --- Broadcast Announcement Workflow with Cancellation ---

@router.callback_query(F.data == "adm_broadcast")
async def callback_adm_broadcast(
    callback: CallbackQuery, state: FSMContext, settings: Settings, repository: DatabaseRepository
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    user_ids = await repository.get_all_active_user_ids()
    await state.set_state(AdminStates.waiting_for_broadcast_content)
    text = (
        "📣 <b>Broadcast Announcement</b>\n\n"
        f"Recipient Pool: <b>{len(user_ids)} active users</b>\n\n"
        "Send the message (text, photo, markdown, etc.) you wish to broadcast to all users."
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast_content)
async def process_broadcast_content(message: Message, state: FSMContext, settings: Settings) -> None:
    if not is_admin_check(message, settings):
        return
    await state.set_state(AdminStates.waiting_for_broadcast_confirm)
    text_preview = message.text or message.caption or "(media message)"
    await state.update_data(
        bcast_msg_id=message.message_id,
        bcast_chat_id=message.chat.id,
        bcast_preview=text_preview[:120],
    )

    kb = get_admin_broadcast_confirm_keyboard()
    await message.reply(
        "👁 <b>Broadcast Message Preview Above</b>\n\n"
        "Do you want to send this broadcast to all active users?",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_bcast_cancel:"))
async def callback_adm_bcast_cancel(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    broadcast_service: Optional[BroadcastService] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    bcast_id_str = callback.data.split(":", 1)[1]
    if bcast_id_str.isdigit() and broadcast_service:
        bcast_id = int(bcast_id_str)
        broadcast_service.cancel_broadcast(bcast_id)
        await repository.log_audit_action(
            admin_id=callback.from_user.id,
            action="broadcast_cancel",
            target=str(bcast_id),
        )
        await callback.answer("🛑 Broadcast cancellation requested. Stopping safely...", show_alert=True)
    else:
        await callback.answer("Unable to cancel broadcast.")


@router.callback_query(F.data == "adm_bcast_confirm")
async def callback_adm_bcast_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    repository: DatabaseRepository,
    broadcast_service: Optional[BroadcastService] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    data = await state.get_data()
    msg_id = data.get("bcast_msg_id")
    from_chat_id = data.get("bcast_chat_id")
    preview = data.get("bcast_preview")
    await state.clear()

    if not msg_id or not from_chat_id:
        await callback.answer("Session expired.", show_alert=True)
        return

    user_ids = await repository.get_all_active_user_ids()
    total_users = len(user_ids)
    if total_users == 0:
        await callback.answer("No active users found to broadcast to.", show_alert=True)
        return

    # Create persistent broadcast history record
    admin_id = callback.from_user.id
    bcast_id = await repository.create_broadcast_record(
        admin_id=admin_id,
        source_chat_id=from_chat_id,
        source_message_id=msg_id,
        text_preview=preview,
        total_targets=total_users,
    )

    await repository.log_audit_action(
        admin_id=admin_id,
        action="broadcast_start",
        target=str(bcast_id),
        details=f"Targets: {total_users}",
    )

    if broadcast_service is None:
        broadcast_service = BroadcastService(repository)

    running_kb = get_admin_broadcast_running_keyboard(bcast_id)
    status_msg = await callback.message.edit_text(
        f"⏳ <b>Dispatching broadcast #{bcast_id}...</b>\n0 / {total_users} delivered",
        reply_markup=running_kb,
        parse_mode="HTML",
    )

    async def update_ui(processed: int, total: int, delivered: int, blocked: int, failed: int):
        remaining = total - processed
        try:
            await status_msg.edit_text(
                f"⏳ <b>Dispatching broadcast #{bcast_id}...</b>\n"
                f"• Processed: <b>{processed} / {total}</b>\n"
                f"• Delivered: <b>{delivered}</b> | Blocked: <b>{blocked}</b> | Failed: <b>{failed}</b>\n"
                f"• Remaining: <b>{remaining}</b>",
                reply_markup=running_kb,
                parse_mode="HTML",
            )
        except Exception:
            pass

    results = await broadcast_service.execute_broadcast(
        bot=callback.bot,
        broadcast_id=bcast_id,
        source_chat_id=from_chat_id,
        source_message_id=msg_id,
        target_user_ids=user_ids,
        progress_callback=update_ui,
    )

    status_icon = "🛑" if results["status"] == "cancelled" else "📣"
    status_title = "Broadcast Cancelled" if results["status"] == "cancelled" else "Broadcast Complete"

    summary = (
        f"{status_icon} <b>{status_title}!</b> (ID #{bcast_id})\n\n"
        f"• Total Targets: <b>{results['total']}</b>\n"
        f"• Successfully Delivered: <b>{results['delivered']}</b>\n"
        f"• Blocked / Deactivated: <b>{results['blocked']}</b>\n"
        f"• Failed / Unreachable: <b>{results['failed']}</b>"
    )
    await status_msg.edit_text(summary, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


# --- Interactive Bot Configuration & Settings Panel ---

@router.callback_query(F.data == "adm_settings")
async def callback_adm_settings(
    callback: CallbackQuery,
    settings: Settings,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    text, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set_mode:"))
async def callback_adm_set_mode(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    target_mode = callback.data.split(":", 1)[1]
    if api_mode_manager is None:
        api_mode_manager = ApiModeManager(callback.bot, settings, repository)

    ok, msg = await api_mode_manager.configure_mode(target_mode, admin_id=callback.from_user.id)
    # Strip HTML tags for alert pop-up if needed, or show concise message
    alert_text = "⚠️ Migration required! See details in settings panel." if api_mode_manager.is_migration_required() else ("⚠️ Restart required to apply changes." if api_mode_manager.is_restart_required() else "Settings updated.")
    await callback.answer(alert_text, show_alert=True)
    if callback.message:
        text, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_set_local_url")
async def callback_adm_set_local_url(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_local_url)
    text = (
        "✏️ <b>Enter Local Bot API Endpoint URL</b>\n\n"
        f"Current: <code>{settings.effective_api_base_url}</code>\n"
        "Default internal Docker endpoint: <code>http://telegram-bot-api:8081</code>\n\n"
        "Send the new HTTP/HTTPS URL below (or /cancel):"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_local_url)
async def process_admin_local_url_input(
    message: Message,
    state: FSMContext,
    settings: Settings,
    repository: DatabaseRepository,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> None:
    if not is_admin_check(message, settings):
        await state.clear()
        return

    url_text = (message.text or "").strip()
    if url_text.lower() in ("/cancel", "cancel"):
        await state.clear()
        text, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
        await message.answer("Editing cancelled.", reply_markup=kb, parse_mode="HTML")
        return

    if api_mode_manager is None:
        api_mode_manager = ApiModeManager(message.bot, settings, repository)

    ok, status_msg = await api_mode_manager.update_local_url(url_text, admin_id=message.from_user.id)
    await state.clear()
    text, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
    await message.answer(f"{status_msg}\n\n" + text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_set_input_mb")
async def callback_adm_set_input_mb(
    callback: CallbackQuery,
    settings: Settings,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    kb = get_file_size_preset_keyboard("input", is_local=settings.is_local_mode)
    text = (
        f"📦 <b>Select Maximum Input File Size</b>\n\n"
        f"Current: <b>{settings.max_input_mb} MB</b>\n"
        f"Mode: {'🖥️ Local Server (up to 2000 MB)' if settings.is_local_mode else '☁️ Cloud Mode (max 20 MB download)'}"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "adm_set_output_mb")
async def callback_adm_set_output_mb(
    callback: CallbackQuery,
    settings: Settings,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    kb = get_file_size_preset_keyboard("output", is_local=settings.is_local_mode)
    text = (
        f"📤 <b>Select Maximum Output File Size</b>\n\n"
        f"Current: <b>{settings.max_output_mb} MB</b>\n"
        f"Mode: {'🖥️ Local Server (up to 2000 MB)' if settings.is_local_mode else '☁️ Cloud Mode (max 50 MB upload)'}"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set_size:"))
async def callback_adm_set_size_preset(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    parts = callback.data.split(":")
    setting_type = parts[1]
    size_mb = int(parts[2])

    if setting_type == "input":
        settings.max_input_mb = size_mb
        await repository.set_system_setting("max_input_mb", str(size_mb))
    else:
        settings.max_output_mb = size_mb
        await repository.set_system_setting("max_output_mb", str(size_mb))

    await repository.log_audit_action(
        admin_id=callback.from_user.id,
        action="update_setting",
        details=f"Changed max_{setting_type}_mb to {size_mb} MB",
    )
    await callback.answer(f"Updated Max {setting_type.title()} to {size_mb} MB!", show_alert=True)
    text, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_set_size_custom:"))
async def callback_adm_set_size_custom(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    setting_type = callback.data.split(":", 1)[1]
    if setting_type == "input":
        await state.set_state(AdminStates.waiting_for_custom_input_mb)
    else:
        await state.set_state(AdminStates.waiting_for_custom_output_mb)

    text = f"✏️ <b>Enter Custom Max {setting_type.title()} Size in MB</b> (1 - 2000):"
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_custom_input_mb)
async def process_custom_input_mb(
    message: Message,
    state: FSMContext,
    settings: Settings,
    repository: DatabaseRepository,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> None:
    if not is_admin_check(message, settings):
        await state.clear()
        return
    text_val = (message.text or "").strip()
    if text_val.lower() in ("/cancel", "cancel"):
        await state.clear()
        t, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
        await message.answer("Cancelled.", reply_markup=kb, parse_mode="HTML")
        return
    if not text_val.isdigit() or not (1 <= int(text_val) <= 2000):
        await message.answer("⚠️ Please enter a valid integer between 1 and 2000.")
        return

    val = int(text_val)
    settings.max_input_mb = val
    await repository.set_system_setting("max_input_mb", str(val))
    await repository.log_audit_action(
        admin_id=message.from_user.id,
        action="update_setting",
        details=f"Changed max_input_mb to {val} MB",
    )
    await state.clear()
    t, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
    await message.answer(f"✅ Max Input Size set to {val} MB!\n\n" + t, reply_markup=kb, parse_mode="HTML")


@router.message(AdminStates.waiting_for_custom_output_mb)
async def process_custom_output_mb(
    message: Message,
    state: FSMContext,
    settings: Settings,
    repository: DatabaseRepository,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> None:
    if not is_admin_check(message, settings):
        await state.clear()
        return
    text_val = (message.text or "").strip()
    if text_val.lower() in ("/cancel", "cancel"):
        await state.clear()
        t, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
        await message.answer("Cancelled.", reply_markup=kb, parse_mode="HTML")
        return
    if not text_val.isdigit() or not (1 <= int(text_val) <= 2000):
        await message.answer("⚠️ Please enter a valid integer between 1 and 2000.")
        return

    val = int(text_val)
    settings.max_output_mb = val
    await repository.set_system_setting("max_output_mb", str(val))
    await repository.log_audit_action(
        admin_id=message.from_user.id,
        action="update_setting",
        details=f"Changed max_output_mb to {val} MB",
    )
    await state.clear()
    t, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
    await message.answer(f"✅ Max Output Size set to {val} MB!\n\n" + t, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_set_toggle:"))
async def callback_adm_set_toggle(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return
    toggle_type = callback.data.split(":", 1)[1]
    if toggle_type == "tech":
        settings.show_technical_info = not settings.show_technical_info
        new_val = settings.show_technical_info
        await repository.set_system_setting("show_technical_info", "1" if new_val else "0")
        label = "Technical Specs in Preview"
    elif toggle_type == "cover":
        settings.send_cover_separately = not settings.send_cover_separately
        new_val = settings.send_cover_separately
        await repository.set_system_setting("send_cover_separately", "1" if new_val else "0")
        label = "Send Cover Separately"
    else:
        await callback.answer()
        return

    await repository.log_audit_action(
        admin_id=callback.from_user.id,
        action="update_setting",
        details=f"Toggled {label} -> {'ON' if new_val else 'OFF'}",
    )
    await callback.answer(f"{label} is now {'ON' if new_val else 'OFF'}!")
    t, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
    if callback.message:
        await callback.message.edit_text(t, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_set_reset")
async def callback_adm_set_reset(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    api_mode_manager: Optional[ApiModeManager] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    if api_mode_manager is None:
        api_mode_manager = ApiModeManager(callback.bot, settings, repository)

    ok, msg = await api_mode_manager.reset_to_env_defaults(admin_id=callback.from_user.id)
    alert_text = "⚠️ Migration required! See details in settings panel." if api_mode_manager.is_migration_required() else ("⚠️ Restart required to apply changes." if api_mode_manager.is_restart_required() else "Settings reset to defaults.")
    await callback.answer(alert_text, show_alert=True)
    t, kb = render_admin_settings(settings, api_mode_manager=api_mode_manager)
    if callback.message:
        await callback.message.edit_text(t, reply_markup=kb, parse_mode="HTML")


# --- Customizable Messages Management ---

@router.callback_query(F.data == "adm_messages")
async def callback_adm_messages(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    message_service: Optional[MessageService] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    if message_service is None:
        message_service = MessageService(repository)

    status_dict = await message_service.get_status_overview()
    kb = get_admin_messages_keyboard(status_dict)
    text = (
        "💬 <b>Customizable Messages</b>\n\n"
        "Select a message below to preview, customize, or reset to default:\n\n"
        "• <b>Welcome Message</b>: Sent upon /start\n"
        "• <b>Must-Join Prompt</b>: Shown when channels must be joined\n"
        "• <b>Help Message</b>: Sent upon /help\n\n"
        "<i>Supported Placeholders:</i>\n"
        "<code>{first_name}</code>, <code>{username}</code>, <code>{user_id}</code>, <code>{bot_name}</code>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_msg_view:"))
async def callback_adm_msg_view(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    message_service: Optional[MessageService] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    msg_key = callback.data.split(":", 1)[1]
    if message_service is None:
        message_service = MessageService(repository)

    try:
        raw_text, is_custom = await message_service.get_raw_message(msg_key)
        status_dict = await message_service.get_status_overview()
        title = status_dict.get(msg_key, {}).get("title", msg_key)
    except Exception as e:
        await callback.answer(f"Error: {e}", show_alert=True)
        return

    status_tag = "⭐ <b>Customized</b>" if is_custom else "⚙️ <b>Default</b>"
    kb = get_admin_message_detail_keyboard(msg_key, is_custom)
    
    text = (
        f"💬 <b>{title}</b>\n"
        f"Status: {status_tag}\n\n"
        f"<b>Current Template:</b>\n"
        f"<pre>{raw_text}</pre>\n\n"
        f"<i>Supported Placeholders:</i>\n"
        f"<code>{{first_name}}</code>, <code>{{username}}</code>, <code>{{user_id}}</code>, <code>{{bot_name}}</code>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_msg_edit:"))
async def callback_adm_msg_edit(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    repository: DatabaseRepository,
    message_service: Optional[MessageService] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    msg_key = callback.data.split(":", 1)[1]
    await state.set_state(AdminStates.waiting_for_custom_message)
    await state.update_data(edit_msg_key=msg_key)

    text = (
        f"✏️ <b>Edit Message Template</b>\n\n"
        f"Send the new text for <code>{msg_key}</code>.\n\n"
        f"• Telegram HTML tags are supported (e.g. <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, <code>&lt;a href=\"...\"&gt;</code>).\n"
        f"• Placeholders: <code>{{first_name}}</code>, <code>{{username}}</code>, <code>{{user_id}}</code>, <code>{{bot_name}}</code>\n\n"
        f"<i>Send your text now or /cancel to abort.</i>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard("adm_messages"), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_custom_message)
async def process_admin_custom_message(
    message: Message,
    state: FSMContext,
    settings: Settings,
    repository: DatabaseRepository,
    message_service: Optional[MessageService] = None,
) -> None:
    if not is_admin_check(message, settings):
        return

    data = await state.get_data()
    msg_key = data.get("edit_msg_key")
    if not msg_key or not message.text:
        await state.clear()
        return

    if message_service is None:
        message_service = MessageService(repository)

    ok, err = await message_service.set_message(
        msg_key=msg_key,
        text=message.text,
        admin_id=message.from_user.id,
    )
    if not ok:
        await message.reply(
            f"❌ <b>Validation Error:</b>\n{err}\n\nPlease fix the markup and try again, or /cancel.",
            parse_mode="HTML",
        )
        return

    await state.clear()
    await message.reply(
        f"✅ <b>Message updated successfully!</b>\n\n"
        f"Template for <code>{msg_key}</code> is now active.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_msg_reset:"))
async def callback_adm_msg_reset(
    callback: CallbackQuery,
    settings: Settings,
    repository: DatabaseRepository,
    message_service: Optional[MessageService] = None,
) -> None:
    if not is_admin_check(callback, settings):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    msg_key = callback.data.split(":", 1)[1]
    if message_service is None:
        message_service = MessageService(repository)

    ok, msg = await message_service.reset_message(msg_key=msg_key, admin_id=callback.from_user.id)
    await callback.answer("Reset to default!", show_alert=True)

    raw_text, is_custom = await message_service.get_raw_message(msg_key)
    status_dict = await message_service.get_status_overview()
    title = status_dict.get(msg_key, {}).get("title", msg_key)
    kb = get_admin_message_detail_keyboard(msg_key, is_custom)
    text = (
        f"💬 <b>{title}</b>\n"
        f"Status: ⚙️ <b>Default</b>\n\n"
        f"<b>Current Template:</b>\n"
        f"<pre>{raw_text}</pre>\n\n"
        f"<i>Supported Placeholders:</i>\n"
        f"<code>{{first_name}}</code>, <code>{{username}}</code>, <code>{{user_id}}</code>, <code>{{bot_name}}</code>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

