"""Tests for database operations."""

import pytest
from app.database.repository import DatabaseRepository


@pytest.mark.asyncio
async def test_required_channels_crud(test_repo: DatabaseRepository):
    ok = await test_repo.add_channel(channel_id='@testchannel', username='testchannel', title='Test Channel')
    assert ok is True

    channels = await test_repo.list_channels()
    assert len(channels) == 1
    assert channels[0].title == 'Test Channel'
    assert channels[0].is_enabled is True

    await test_repo.set_channel_enabled('@testchannel', False)
    enabled = await test_repo.list_channels(enabled_only=True)
    assert len(enabled) == 0

    await test_repo.set_channel_enabled('@testchannel', True)
    enabled = await test_repo.list_channels(enabled_only=True)
    assert len(enabled) == 1

    del_ok = await test_repo.remove_channel('@testchannel')
    assert del_ok is True
    assert len(await test_repo.list_channels()) == 0


@pytest.mark.asyncio
async def test_whitelist_and_bans(test_repo: DatabaseRepository):
    # Whitelist
    await test_repo.add_to_whitelist(user_id=12345, username='alice', reason='VIP')
    assert await test_repo.is_whitelisted(12345) is True
    assert await test_repo.is_whitelisted(99999) is False

    # Ban
    await test_repo.ban_user(user_id=54321, username='spammer', reason='Abuse')
    assert await test_repo.is_banned(54321) is True
    assert await test_repo.is_banned(12345) is False
