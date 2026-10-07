"""Tests for MustJoinService."""

from unittest.mock import AsyncMock, MagicMock
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberMember, ChatMemberLeft
import pytest

from app.database.repository import DatabaseRepository
from app.services.must_join_service import MustJoinService


@pytest.mark.asyncio
async def test_must_join_evaluation(test_repo: DatabaseRepository):
    service = MustJoinService(test_repo)

    # 1. No required channels configured -> always True
    mock_bot = MagicMock()
    has_joined, missing = await service.check_user_membership(mock_bot, 12345)
    assert has_joined is True
    assert len(missing) == 0

    # 2. Add required channels
    await test_repo.add_channel("@chan1", username="chan1")
    await test_repo.add_channel("@chan2", username="chan2")

    # Case A: User is member of both
    mock_bot.get_chat_member = AsyncMock(
        return_value=MagicMock(status=ChatMemberStatus.MEMBER)
    )
    has_joined, missing = await service.check_user_membership(mock_bot, 12345)
    assert has_joined is True
    assert len(missing) == 0

    # Case B: User left chan2
    async def fake_get_chat_member(chat_id, user_id):
        if "chan2" in chat_id:
            return MagicMock(status=ChatMemberStatus.LEFT)
        return MagicMock(status=ChatMemberStatus.MEMBER)

    mock_bot.get_chat_member = AsyncMock(side_effect=fake_get_chat_member)
    has_joined, missing = await service.check_user_membership(mock_bot, 12345)
    assert has_joined is False
    assert len(missing) == 1
    assert missing[0].channel_id == "@chan2"


@pytest.mark.asyncio
async def test_middleware_access_control(test_repo: DatabaseRepository):
    from app.bot.middleware.must_join_middleware import MustJoinMiddleware
    from app.config import Settings

    service = MustJoinService(test_repo)
    middleware = MustJoinMiddleware(service)
    await test_repo.add_channel("@mustjoin", username="mustjoin")

    settings = Settings(bot_token="test", admin_ids=[999])
    mock_bot = MagicMock()
    mock_bot.get_chat_member = AsyncMock(return_value=MagicMock(status=ChatMemberStatus.LEFT))

    handler_called = False

    async def dummy_handler(event, data):
        nonlocal handler_called
        handler_called = True
        return "OK"

    from aiogram.types import Message

    # Case 1: Banned user -> blocked immediately
    await test_repo.ban_user(user_id=666, reason="Bad actor")
    mock_event = MagicMock(spec=Message)
    mock_event.text = "/start_process"
    mock_event.reply = AsyncMock()

    data = {
        "event_from_user": MagicMock(id=666, is_bot=False),
        "bot": mock_bot,
        "settings": settings,
    }
    handler_called = False
    result = await middleware(dummy_handler, mock_event, data)
    assert result is None
    assert handler_called is False
    mock_event.reply.assert_called_once()
    assert "banned" in mock_event.reply.call_args[0][0].lower()

    # Case 2: Whitelisted user -> bypasses must-join check
    await test_repo.add_to_whitelist(user_id=777, reason="VIP")
    data["event_from_user"] = MagicMock(id=777, is_bot=False)
    handler_called = False
    result = await middleware(dummy_handler, mock_event, data)
    assert result == "OK"
    assert handler_called is True

    # Case 3: Admin -> bypasses must-join check
    data["event_from_user"] = MagicMock(id=999, is_bot=False)
    handler_called = False
    result = await middleware(dummy_handler, mock_event, data)
    assert result == "OK"
    assert handler_called is True

    # Case 4: Normal user not joined -> prompt must-join
    mock_event.reply.reset_mock()
    data["event_from_user"] = MagicMock(id=888, is_bot=False)
    handler_called = False
    result = await middleware(dummy_handler, mock_event, data)
    assert result is None
    assert handler_called is False
    mock_event.reply.assert_called_once()
    assert "join our channel" in mock_event.reply.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_must_join_immediate_on_start_and_verify_welcome(test_repo: DatabaseRepository):
    from app.bot.middleware.must_join_middleware import MustJoinMiddleware
    from app.bot.handlers.common import callback_must_join_verify
    from app.services.message_service import MessageService
    from app.config import Settings
    from aiogram.types import Message, CallbackQuery

    service = MustJoinService(test_repo)
    msg_service = MessageService(test_repo)
    middleware = MustJoinMiddleware(service, msg_service)
    await test_repo.add_channel("@musicchannel", title="Music Channel", username="musicchannel")

    settings = Settings(bot_token="test", admin_ids=[999])
    mock_bot = MagicMock()
    # User is not a member initially
    mock_bot.get_chat_member = AsyncMock(return_value=MagicMock(status=ChatMemberStatus.LEFT))

    handler_called = False
    async def dummy_start_handler(event, data):
        nonlocal handler_called
        handler_called = True
        return "STARTED"

    # 1. Unjoined user sends /start -> Middleware blocks and prompts must-join immediately!
    start_msg = MagicMock(spec=Message)
    start_msg.text = "/start"
    start_msg.reply = AsyncMock()

    user = MagicMock(id=12345, is_bot=False, first_name="John")
    data = {
        "event_from_user": user,
        "bot": mock_bot,
        "settings": settings,
    }

    result = await middleware(dummy_start_handler, start_msg, data)
    assert result is None
    assert handler_called is False
    start_msg.reply.assert_called_once()
    prompt_text = start_msg.reply.call_args[0][0]
    assert "join our channel" in prompt_text.lower()

    # 2. User joins the channel and taps "I've joined" (must_join_verify)
    mock_bot.get_chat_member = AsyncMock(return_value=MagicMock(status=ChatMemberStatus.MEMBER))

    cb = MagicMock(spec=CallbackQuery)
    cb.data = "must_join_verify"
    cb.from_user = user
    cb.bot = mock_bot
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()

    await callback_must_join_verify(cb, service, msg_service)
    cb.answer.assert_called_once()
    assert "confirmed" in cb.answer.call_args[0][0].lower()
    cb.message.edit_text.assert_called_once()
    verified_text = cb.message.edit_text.call_args[0][0]
    assert "Membership Verified" in verified_text
    assert "Welcome John!" in verified_text


