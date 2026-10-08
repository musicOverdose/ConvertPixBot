"""Tests for Telegram Admin Panel handlers and security permissions."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

from app.bot.handlers.admin_handlers import (
    cmd_admin,
    cmd_ban,
    cmd_unban,
    cmd_whitelist,
    cmd_stats,
    cmd_reload_config,
    is_admin_check,
)
from app.config import Settings
from app.database.repository import DatabaseRepository


@pytest.fixture
def fsm_context():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=100, user_id=100)
    return FSMContext(storage=storage, key=key)


@pytest.mark.asyncio
async def test_admin_permission_check():
    settings = Settings(bot_token="test", admin_ids=[1001, 1002])

    # Admin message
    msg_admin = MagicMock()
    msg_admin.from_user.id = 1001
    assert is_admin_check(msg_admin, settings) is True

    # Non-admin message
    msg_user = MagicMock()
    msg_user.from_user.id = 9999
    assert is_admin_check(msg_user, settings) is False


@pytest.mark.asyncio
async def test_cmd_admin_dashboard(fsm_context):
    settings = Settings(bot_token="test", admin_ids=[1001])

    # Admin execution
    msg = MagicMock()
    msg.from_user.id = 1001
    msg.answer = AsyncMock()

    await cmd_admin(msg, fsm_context, settings)
    msg.answer.assert_called_once()
    assert f"{settings.bot_name} Admin Dashboard" in msg.answer.call_args[0][0]

    # Non-admin execution
    msg_unauthorized = MagicMock()
    msg_unauthorized.from_user.id = 9999
    msg_unauthorized.answer = AsyncMock()

    await cmd_admin(msg_unauthorized, fsm_context, settings)
    msg_unauthorized.answer.assert_not_called()


@pytest.mark.asyncio
async def test_admin_whitelist_and_ban_commands(test_repo: DatabaseRepository, fsm_context):
    settings = Settings(bot_token="test", admin_ids=[1001])

    msg = MagicMock()
    msg.from_user.id = 1001
    msg.answer = AsyncMock()

    # 1. Ban user
    msg.text = "/ban 777 spammer"
    await cmd_ban(msg, settings, test_repo)
    assert await test_repo.is_banned(777) is True
    assert "banned" in msg.answer.call_args[0][0].lower()

    # 2. Unban user
    msg.text = "/unban 777"
    await cmd_unban(msg, settings, test_repo)
    assert await test_repo.is_banned(777) is False
    assert "unbanned" in msg.answer.call_args[0][0].lower()

    # 3. Whitelist user
    msg.text = "/whitelist add 888 VIP"
    await cmd_whitelist(msg, settings, test_repo)
    assert await test_repo.is_whitelisted(888) is True
    assert "whitelisted" in msg.answer.call_args[0][0].lower()

    # 4. Remove from whitelist
    msg.text = "/whitelist del 888"
    await cmd_whitelist(msg, settings, test_repo)
    assert await test_repo.is_whitelisted(888) is False


@pytest.mark.asyncio
async def test_admin_stats_and_reload(test_repo: DatabaseRepository):
    settings = Settings(bot_token="test", admin_ids=[1001])

    msg = MagicMock()
    msg.from_user.id = 1001
    msg.answer = AsyncMock()

    # Stats
    await cmd_stats(msg, settings, test_repo)
    msg.answer.assert_called_once()
    assert "Statistics" in msg.answer.call_args[0][0]

    # Reload config
    msg.answer.reset_mock()
    await cmd_reload_config(msg, settings)
    msg.answer.assert_called_once()
    assert "reloaded" in msg.answer.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_admin_whitelist_title_and_info_display(test_repo: DatabaseRepository, fsm_context):
    from app.database.models import WhitelistedUser, BannedUser
    from app.bot.keyboards.admin_menu import get_admin_whitelist_keyboard, get_admin_banlist_keyboard
    from app.bot.handlers.admin_handlers import (
        callback_adm_wl_info,
        callback_adm_ban_info,
        callback_adm_whitelist,
        _render_whitelist_text,
        _render_banlist_text,
    )

    settings = Settings(bot_token="test", admin_ids=[1001])

    # 1. Verify keyboard title formatting
    user_with_title = WhitelistedUser(user_id=123, username="alex", reason="Alex VIP Producer")
    user_with_user = WhitelistedUser(user_id=456, username="coolguy", reason=None)
    user_id_only = WhitelistedUser(user_id=789, username=None, reason=None)
    user_long_title = WhitelistedUser(user_id=999, username=None, reason="Super Long Title Exceeding Max Length Limit")

    kb = get_admin_whitelist_keyboard([user_with_title, user_with_user, user_id_only, user_long_title])
    assert kb.inline_keyboard[0][0].text == "⭐ Alex VIP Producer"
    assert kb.inline_keyboard[1][0].text == "⭐ @coolguy"
    assert kb.inline_keyboard[2][0].text == "⭐ ID: 789"
    assert kb.inline_keyboard[3][0].text.endswith("...")

    # 2. Ban keyboard formatting
    banned_with_reason = BannedUser(user_id=111, username="badguy", reason="Spammer Bot")
    banned_kb = get_admin_banlist_keyboard([banned_with_reason])
    assert banned_kb.inline_keyboard[0][0].text == "🚫 Spammer Bot"

    # 3. Add to repo and test callback_adm_wl_info popup
    await test_repo.add_to_whitelist(user_id=123, username="alex", reason="Alex VIP Producer")
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.data = "adm_wl_info:123"
    cb.answer = AsyncMock()

    await callback_adm_wl_info(cb, settings, test_repo)
    cb.answer.assert_called_once()
    alert_text = cb.answer.call_args[0][0]
    assert "Alex VIP Producer" in alert_text
    assert "123" in alert_text
    assert "@alex" in alert_text
    assert cb.answer.call_args[1]["show_alert"] is True

    # 4. Text render helper displays title prominently
    text = _render_whitelist_text([user_with_title, user_id_only])
    assert "• <b>Alex VIP Producer</b> (@alex • <code>123</code>)" in text
    assert "• <code>789</code>" in text


@pytest.mark.asyncio
async def test_admin_channels_management_and_sync(test_repo: DatabaseRepository):
    from app.database.models import RequiredChannel
    from app.bot.keyboards.admin_menu import get_admin_channels_keyboard
    from app.bot.handlers.admin_handlers import (
        callback_adm_ch_info,
        callback_adm_ch_sync,
        callback_adm_wl_sync,
        callback_adm_ban_sync,
        _render_channels_text,
    )

    settings = Settings(bot_token="test", admin_ids=[1001])

    # 1. Channels keyboard formatting
    ch1 = RequiredChannel(channel_id="-100123456789", title="Music Channel", username="music_chan", is_enabled=True)
    ch2 = RequiredChannel(channel_id="-100987654321", title=None, username=None, is_enabled=False)
    kb = get_admin_channels_keyboard([ch1, ch2])

    # Row 1: [📢 Music Channel], [🟢 On], [🗑]
    assert kb.inline_keyboard[0][0].text == "📢 Music Channel"
    assert kb.inline_keyboard[0][1].text == "🟢 On"
    assert kb.inline_keyboard[0][2].text == "🗑"

    # Row 2: [📢 -100987654321], [🔴 Off], [🗑]
    assert kb.inline_keyboard[1][0].text == "📢 -100987654321"
    assert kb.inline_keyboard[1][1].text == "🔴 Off"

    # Action buttons: Add Channel and Sync Info
    assert kb.inline_keyboard[2][0].text == "➕ Add Channel"
    assert kb.inline_keyboard[2][1].text == "🔄 Sync Info"

    # 2. Add channel to repo and test info popup
    await test_repo.add_channel(channel_id="-100123456789", title="Music Channel", username="music_chan")
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.data = "adm_ch_info:-100123456789"
    cb.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator"))
    cb.answer = AsyncMock()

    await callback_adm_ch_info(cb, settings, test_repo)
    cb.answer.assert_called_once()
    alert_text = cb.answer.call_args[0][0]
    assert "Music Channel" in alert_text
    assert "-100123456789" in alert_text
    assert "@music_chan" in alert_text

    # 3. Test _render_channels_text
    summary = _render_channels_text([ch1, ch2])
    assert "Music Channel" in summary
    assert "Active" in summary
    assert "Disabled" in summary

    # 4. Test callback_adm_ch_sync
    mock_chat = MagicMock(id=-100123456789, title="Updated Title", username="music_chan", invite_link="https://t.me/music_chan")
    cb.bot.get_chat = AsyncMock(return_value=mock_chat)
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    await callback_adm_ch_sync(cb, settings, test_repo)
    cb.answer.assert_called()
    channels = await test_repo.list_channels()
    assert channels[0].title == "Updated Title"


@pytest.mark.asyncio
async def test_admin_settings_menu_and_toggles(test_repo: DatabaseRepository):
    from app.bot.handlers.admin_handlers import (
        render_admin_settings,
        callback_adm_settings,
        callback_adm_set_toggle,
        callback_adm_set_size_preset,
    )

    settings = Settings(bot_token="test", admin_ids=[1001])

    # 1. Test render_admin_settings directly - must NOT raise AttributeError
    text, kb = render_admin_settings(settings)
    assert "Bot Configuration & API Settings" in text
    assert "Image Inspection Details" in text
    assert "Preview Photo Delivery" in text
    assert kb is not None

    # 2. Test callback_adm_settings
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.data = "adm_settings"
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()

    await callback_adm_settings(cb, settings)
    cb.message.edit_text.assert_called_once()
    assert "Bot Configuration & API Settings" in cb.message.edit_text.call_args[0][0]

    # 3. Test toggling tech info (Image Inspection Details)
    cb.reset_mock()
    cb.data = "adm_set_toggle:tech"
    initial_tech = getattr(settings, "show_technical_info", True)

    await callback_adm_set_toggle(cb, settings, test_repo)
    assert settings.show_technical_info == (not initial_tech)
    saved_tech = await test_repo.get_system_setting("show_technical_info")
    assert saved_tech == ("1" if settings.show_technical_info else "0")

    # 4. Test toggling cover (Preview Photo Delivery)
    cb.reset_mock()
    cb.data = "adm_set_toggle:cover"
    initial_cover = getattr(settings, "send_cover_separately", True)

    await callback_adm_set_toggle(cb, settings, test_repo)
    assert settings.send_cover_separately == (not initial_cover)
    saved_cover = await test_repo.get_system_setting("send_cover_separately")
    assert saved_cover == ("1" if settings.send_cover_separately else "0")

    # 5. Test size preset
    cb.reset_mock()
    cb.data = "adm_set_size:input:50"
    await callback_adm_set_size_preset(cb, settings, test_repo)
    assert settings.max_input_mb == 50
    assert await test_repo.get_system_setting("max_input_mb") == "50"


@pytest.mark.asyncio
async def test_admin_stats_callback_and_gc_ops(test_repo: DatabaseRepository, tmp_path):
    from app.services.job_manager import JobManager
    from app.bot.handlers.admin_handlers import (
        callback_adm_stats,
        callback_adm_cleanup,
        callback_adm_backup,
        callback_adm_maint_toggle,
        callback_adm_audit,
    )

    settings = Settings(
        bot_token="test",
        admin_ids=[1001],
        jobs_dir=tmp_path / "jobs",
        backups_dir=tmp_path / "backups",
    )
    job_mgr = JobManager(base_jobs_dir=settings.jobs_dir)

    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()

    # 1. Stats callback
    cb.data = "adm_stats"
    await callback_adm_stats(cb, settings, test_repo)
    cb.message.edit_text.assert_called_once()
    assert f"{settings.bot_name} Operational Statistics" in cb.message.edit_text.call_args[0][0]

    # 2. Cleanup GC callback
    cb.reset_mock()
    cb.data = "adm_cleanup"
    await callback_adm_cleanup(cb, settings, job_mgr, test_repo)
    cb.message.edit_text.assert_called_once()
    assert "Garbage Collection Complete" in cb.message.edit_text.call_args[0][0]

    # 3. Backup callback
    cb.reset_mock()
    cb.data = "adm_backup"
    await callback_adm_backup(cb, settings, test_repo)
    cb.message.edit_text.assert_called_once()
    assert "Database Online Backup Complete" in cb.message.edit_text.call_args[0][0]

    # 4. Maintenance toggle callback
    cb.reset_mock()
    cb.data = "adm_maint_toggle"
    await callback_adm_maint_toggle(cb, settings, test_repo, job_mgr)
    assert await test_repo.is_maintenance_mode() is True
    assert job_mgr.is_maintenance_mode is True

    # 5. Audit logs callback
    cb.reset_mock()
    cb.data = "adm_audit:0"
    await callback_adm_audit(cb, settings, test_repo)
    cb.message.edit_text.assert_called_once()
    assert "Admin Audit Trail" in cb.message.edit_text.call_args[0][0]


@pytest.mark.asyncio
async def test_admin_messages_menu(test_repo: DatabaseRepository):
    from app.services.message_service import MessageService
    from app.bot.handlers.admin_handlers import (
        callback_adm_messages,
        callback_adm_msg_view,
        callback_adm_msg_reset,
    )

    settings = Settings(bot_token="test", admin_ids=[1001])
    msg_service = MessageService(test_repo)

    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()

    # 1. Messages menu
    cb.data = "adm_messages"
    await callback_adm_messages(cb, settings, test_repo, msg_service)
    cb.message.edit_text.assert_called_once()
    assert "Customizable Messages" in cb.message.edit_text.call_args[0][0]

    # 2. View message detail
    cb.reset_mock()
    cb.data = "adm_msg_view:welcome"
    await callback_adm_msg_view(cb, settings, test_repo, msg_service)
    cb.message.edit_text.assert_called_once()
    assert "Welcome Message" in cb.message.edit_text.call_args[0][0]

    # 3. Reset message
    cb.reset_mock()
    cb.data = "adm_msg_reset:welcome"
    await callback_adm_msg_reset(cb, settings, test_repo, msg_service)
    cb.answer.assert_called_once()



