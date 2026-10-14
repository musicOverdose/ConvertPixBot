"""Comprehensive tests for Event-Driven Must-Join with Shared Redis and Auto-Unblock."""

import time
from unittest.mock import AsyncMock, MagicMock
from aiogram.enums import ChatMemberStatus
from aiogram.types import Message
import pytest

from app.database.models import RequiredChannel
from app.database.repository import DatabaseRepository
from app.services.must_join_redis import (
    MustJoinRedisClient,
    MEMBER_CACHE_TTL,
    NOT_MEMBER_CACHE_TTL,
)
from app.services.must_join_service import MustJoinService
from app.bot.keyboards.must_join_menu import get_must_join_keyboard
from app.bot.middleware.must_join_middleware import MustJoinMiddleware
from app.bot.handlers.chat_member_handlers import handle_chat_member_updated
from app.services.message_service import MessageService
from app.config import Settings


class FakePipeline:
    def __init__(self, fake):
        self.fake = fake
        self.ops = []

    def set(self, key, value, ex=None):
        self.ops.append((key, value, ex))
        return self

    async def execute(self):
        for key, value, ex in self.ops:
            await self.fake.set(key, value, ex=ex)
        return []


class FakeRedis:
    """In-memory Redis mock for isolated, lightning-fast test execution."""

    def __init__(self):
        self.data = {}
        self.sets = {}
        self.ttls = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = str(value)
        if ex:
            self.ttls[key] = ex

    async def delete(self, key):
        self.data.pop(key, None)
        self.ttls.pop(key, None)

    async def sismember(self, key, member):
        return str(member) in self.sets.get(key, set())

    async def sadd(self, key, *members):
        if key not in self.sets:
            self.sets[key] = set()
        for m in members:
            self.sets[key].add(str(m))

    def pipeline(self):
        return FakePipeline(self)

    async def aclose(self):
        pass


@pytest.fixture
def fake_redis_client():
    fake = FakeRedis()
    client = MustJoinRedisClient(
        redis_url="redis://localhost:6379/1",
        bot_prefix="convertpix",
        client=fake,
    )
    return client, fake


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


def test_must_join_keyboard_has_no_verify_button():
    """Verify 'I've joined' button is completely removed and only channel links exist."""
    ch1 = RequiredChannel(channel_id="-1001", title="Channel One", invite_link="https://t.me/one")
    ch2 = RequiredChannel(channel_id="-1002", title="Channel Two", username="two")

    kb = get_must_join_keyboard([ch1, ch2])
    assert len(kb.inline_keyboard) == 2

    # Verify buttons are only channel links
    for row in kb.inline_keyboard:
        btn = row[0]
        assert btn.url is not None
        assert btn.callback_data is None
        assert "I've joined" not in btn.text


@pytest.mark.asyncio
async def test_must_join_redis_caching_and_protection(test_repo: DatabaseRepository, fake_redis_client):
    redis_client, fake = fake_redis_client
    service = MustJoinService(test_repo, redis_client=redis_client)

    await test_repo.add_channel("-100999", title="Test Channel", username="test_chan")
    user_id = 55555

    # 1. Write-amplification protection: user is not known yet
    assert await redis_client.is_known_user(user_id) is False
    await redis_client.mark_user_known(user_id)
    assert await redis_client.is_known_user(user_id) is True

    # 2. Cache miss -> calls Telegram Bot API and caches as MEMBER with 24h TTL
    mock_bot = MagicMock()
    mock_bot.get_chat_member = AsyncMock(return_value=MagicMock(status=ChatMemberStatus.MEMBER))

    has_joined, missing = await service.check_user_membership(mock_bot, user_id)
    assert has_joined is True
    assert len(missing) == 0
    assert mock_bot.get_chat_member.call_count == 1

    # Verify Redis key and TTL
    cached = await redis_client.get_cached_membership(user_id, "-100999")
    assert cached == "MEMBER"
    assert fake.ttls.get("convertpix:must_join:55555:-100999") == MEMBER_CACHE_TTL

    # 3. Cache hit -> does NOT call Telegram Bot API again
    mock_bot.get_chat_member.reset_mock()
    has_joined, missing = await service.check_user_membership(mock_bot, user_id)
    assert has_joined is True
    mock_bot.get_chat_member.assert_not_called()

    # 4. Out-of-order protection: incoming older timestamp rejected
    now_ts = time.time()
    await redis_client.set_cached_membership(user_id, "-100999", "MEMBER", update_timestamp=now_ts)

    # Attempt setting with an older timestamp (e.g. now_ts - 50)
    accepted = await redis_client.set_cached_membership(
        user_id, "-100999", "NOT_MEMBER", update_timestamp=now_ts - 50
    )
    assert accepted is False
    # Status remains MEMBER
    assert await redis_client.get_cached_membership(user_id, "-100999") == "MEMBER"

    # Attempt setting with a newer timestamp -> accepted and TTL is 30s for NOT_MEMBER
    accepted = await redis_client.set_cached_membership(
        user_id, "-100999", "NOT_MEMBER", update_timestamp=now_ts + 10
    )
    assert accepted is True
    assert await redis_client.get_cached_membership(user_id, "-100999") == "NOT_MEMBER"
    assert fake.ttls.get("convertpix:must_join:55555:-100999") == NOT_MEMBER_CACHE_TTL


@pytest.mark.asyncio
async def test_middleware_access_control(test_repo: DatabaseRepository, fake_redis_client):
    redis_client, fake = fake_redis_client
    service = MustJoinService(test_repo, redis_client=redis_client)
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

    # 1. Banned user -> blocked immediately
    await test_repo.ban_user(user_id=666, reason="Bad actor")
    mock_event = MagicMock(spec=Message)
    mock_event.text = "/start"
    mock_event.reply = AsyncMock()

    data = {
        "event_from_user": MagicMock(id=666, is_bot=False),
        "bot": mock_bot,
        "settings": settings,
    }
    result = await middleware(dummy_handler, mock_event, data)
    assert result is None
    assert handler_called is False
    mock_event.reply.assert_called_once()
    assert "banned" in mock_event.reply.call_args[0][0].lower()

    # 2. Whitelisted user -> bypasses must-join check
    await test_repo.add_to_whitelist(user_id=777, reason="VIP")
    data["event_from_user"] = MagicMock(id=777, is_bot=False)
    handler_called = False
    result = await middleware(dummy_handler, mock_event, data)
    assert result == "OK"
    assert handler_called is True

    # 3. Admin -> bypasses must-join check
    data["event_from_user"] = MagicMock(id=999, is_bot=False)
    handler_called = False
    result = await middleware(dummy_handler, mock_event, data)
    assert result == "OK"
    assert handler_called is True

    # 4. Normal user not joined -> prompt must-join & saves prompt message ID in Redis
    prompt_sent_msg = MagicMock()
    prompt_sent_msg.chat.id = 12345
    prompt_sent_msg.message_id = 9876
    mock_event.reply = AsyncMock(return_value=prompt_sent_msg)

    data["event_from_user"] = MagicMock(id=888, is_bot=False)
    handler_called = False
    result = await middleware(dummy_handler, mock_event, data)
    assert result is None
    assert handler_called is False
    mock_event.reply.assert_called_once()
    assert "join our channel" in mock_event.reply.call_args[0][0].lower()

    # Verify prompt was saved in Redis: convertpix:must_join_msg:888 = "12345:9876"
    saved_prompt = await redis_client.get_and_clear_must_join_prompt(888)
    assert saved_prompt == (12345, 9876)


@pytest.mark.asyncio
async def test_chat_member_updated_join_auto_unblock(test_repo: DatabaseRepository, fake_redis_client):
    """Full end-to-end event-driven test: join triggers prompt deletion & welcome delivery."""
    redis_client, fake = fake_redis_client
    service = MustJoinService(test_repo, redis_client=redis_client)
    msg_service = MessageService(test_repo)
    await test_repo.add_channel("-100111", title="VIP Channel", username="vip_chan")

    user_id = 4444
    user_mock = MagicMock(id=user_id, is_bot=False, first_name="Alice")

    # Step 1: User is prompted and prompt message saved in Redis
    await redis_client.mark_user_known(user_id)
    await redis_client.save_must_join_prompt(user_id=user_id, chat_id=user_id, message_id=3001)

    # Step 2: User joins channel -> Telegram dispatches ChatMemberUpdated
    mock_bot = MagicMock()
    mock_bot.delete_message = AsyncMock()
    mock_bot.send_message = AsyncMock()

    event = MagicMock()
    event.chat.id = -100111
    event.chat.title = "VIP Channel"
    event.chat.username = "vip_chan"
    event.date.timestamp = MagicMock(return_value=time.time())

    new_member = MagicMock()
    new_member.user = user_mock
    new_member.status = ChatMemberStatus.MEMBER
    event.new_chat_member = new_member

    await handle_chat_member_updated(
        event=event,
        bot=mock_bot,
        must_join_service=service,
        message_service=msg_service,
    )

    # 1. Prompt message must be deleted
    mock_bot.delete_message.assert_called_once_with(chat_id=user_id, message_id=3001)

    # 2. Welcome message must be delivered to user's chat
    mock_bot.send_message.assert_called_once()
    send_args = mock_bot.send_message.call_args
    assert send_args[1]["chat_id"] == user_id
    assert "Alice" in send_args[1]["text"]

    # 3. Redis prompt key must be deleted
    assert await redis_client.get_and_clear_must_join_prompt(user_id) is None

    # 4. Redis membership cache must be MEMBER with 24h TTL
    cached = await redis_client.get_cached_membership(user_id, "-100111")
    assert cached == "MEMBER"
    assert fake.ttls.get(f"convertpix:must_join:{user_id}:-100111") == MEMBER_CACHE_TTL


@pytest.mark.asyncio
async def test_chat_member_updated_write_amplification_protection(test_repo: DatabaseRepository, fake_redis_client):
    """Verify that updates for unknown users (who never used the bot) are ignored."""
    redis_client, fake = fake_redis_client
    service = MustJoinService(test_repo, redis_client=redis_client)
    await test_repo.add_channel("-100222", title="Public Channel")

    unknown_user_id = 999999
    unknown_user = MagicMock(id=unknown_user_id, is_bot=False)

    mock_bot = MagicMock()
    mock_bot.delete_message = AsyncMock()
    mock_bot.send_message = AsyncMock()

    event = MagicMock()
    event.chat.id = -100222
    event.date.timestamp = MagicMock(return_value=time.time())
    new_member = MagicMock()
    new_member.user = unknown_user
    new_member.status = ChatMemberStatus.MEMBER
    event.new_chat_member = new_member

    # User is not in known_users
    await handle_chat_member_updated(
        event=event,
        bot=mock_bot,
        must_join_service=service,
    )

    # No writes to Redis, no messages sent
    assert await redis_client.get_cached_membership(unknown_user_id, "-100222") is None
    mock_bot.delete_message.assert_not_called()
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_chat_member_updated_leave_and_kick(test_repo: DatabaseRepository, fake_redis_client):
    """Verify that leave/kick sets NOT_MEMBER with 30s TTL."""
    redis_client, fake = fake_redis_client
    service = MustJoinService(test_repo, redis_client=redis_client)
    await test_repo.add_channel("-100333", title="Channel Three")

    user_id = 112233
    user_mock = MagicMock(id=user_id, is_bot=False)
    await redis_client.mark_user_known(user_id)

    mock_bot = MagicMock()

    event = MagicMock()
    event.chat.id = -100333
    event.date.timestamp = MagicMock(return_value=time.time())
    new_member = MagicMock()
    new_member.user = user_mock
    new_member.status = ChatMemberStatus.LEFT
    event.new_chat_member = new_member

    await handle_chat_member_updated(
        event=event,
        bot=mock_bot,
        must_join_service=service,
    )

    cached = await redis_client.get_cached_membership(user_id, "-100333")
    assert cached == "NOT_MEMBER"
    assert fake.ttls.get(f"convertpix:must_join:{user_id}:-100333") == NOT_MEMBER_CACHE_TTL
