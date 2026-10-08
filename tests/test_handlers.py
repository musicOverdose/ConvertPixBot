"""Integration and handler tests for Convert Pix Bot."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from PIL import Image

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

from app.config import Settings
from app.database.repository import DatabaseRepository
from app.services.file_acquisition import FileAcquisitionService
from app.services.job_manager import JobManager
from app.services.queue_manager import QueueManager
from app.services.rate_limiter import RateLimiter
from app.bot.handlers.job_handler import handle_media_upload, callback_convert_format
from app.bot.handlers.common import cmd_cancel


@pytest.fixture
def fsm_ctx():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=100, user_id=100)
    return FSMContext(storage=storage, key=key)


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_token="test_token",
        admin_ids=[9999],
        temp_dir=tmp_path / "temp",
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def test_job_manager(tmp_path: Path) -> JobManager:
    return JobManager(base_jobs_dir=tmp_path / "jobs")


@pytest.fixture
def test_rate_limiter() -> RateLimiter:
    return RateLimiter(max_requests=100, window_seconds=60)


@pytest.fixture
def mock_file_acquisition(sample_png: Path) -> FileAcquisitionService:
    service = MagicMock(spec=FileAcquisitionService)
    async def fake_acquire(bot, file_or_id, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(sample_png.read_bytes())
        return destination
    service.acquire_file = AsyncMock(side_effect=fake_acquire)
    return service


@pytest.mark.asyncio
async def test_animated_sticker_rejection(
    fsm_ctx,
    test_settings,
    test_job_manager,
    test_repo: DatabaseRepository,
    test_rate_limiter,
):
    msg = MagicMock()
    msg.from_user.id = 1234
    msg.from_user.username = "testuser"
    msg.sticker.is_animated = True
    msg.sticker.is_video = False
    msg.answer = AsyncMock()

    file_acq = MagicMock(spec=FileAcquisitionService)

    await handle_media_upload(
        message=msg,
        state=fsm_ctx,
        settings=test_settings,
        job_manager=test_job_manager,
        repository=test_repo,
        rate_limiter=test_rate_limiter,
        file_acquisition=file_acq,
    )

    msg.answer.assert_called_once()
    assert "Animated and video stickers are not supported" in msg.answer.call_args[0][0]
    assert test_job_manager.get_active_jobs_count() == 0


@pytest.mark.asyncio
async def test_video_sticker_rejection(
    fsm_ctx,
    test_settings,
    test_job_manager,
    test_repo: DatabaseRepository,
    test_rate_limiter,
):
    msg = MagicMock()
    msg.from_user.id = 1234
    msg.from_user.username = "testuser"
    msg.sticker.is_animated = False
    msg.sticker.is_video = True
    msg.answer = AsyncMock()

    file_acq = MagicMock(spec=FileAcquisitionService)

    await handle_media_upload(
        message=msg,
        state=fsm_ctx,
        settings=test_settings,
        job_manager=test_job_manager,
        repository=test_repo,
        rate_limiter=test_rate_limiter,
        file_acquisition=file_acq,
    )

    msg.answer.assert_called_once()
    assert "Animated and video stickers are not supported" in msg.answer.call_args[0][0]
    assert test_job_manager.get_active_jobs_count() == 0


@pytest.mark.asyncio
async def test_static_sticker_upload_and_inspection(
    fsm_ctx,
    test_settings,
    test_job_manager,
    test_repo: DatabaseRepository,
    test_rate_limiter,
    tmp_path: Path,
):
    # Create static sticker WebP
    stk_path = tmp_path / "sticker.webp"
    Image.new("RGBA", (512, 512), (0, 100, 200, 128)).save(stk_path, format="WEBP")

    msg = MagicMock()
    msg.from_user.id = 1234
    msg.from_user.username = "testuser"
    msg.from_user.first_name = "Test"
    msg.from_user.last_name = None
    msg.chat.id = 1234
    msg.sticker = MagicMock(
        is_animated=False,
        is_video=False,
        file_id="stk_id_123",
        file_unique_id="unique_stk",
        file_size=stk_path.stat().st_size,
    )
    msg.photo = None
    msg.document = None
    msg.answer = AsyncMock()

    file_acq = MagicMock(spec=FileAcquisitionService)
    async def fake_acquire(bot, file_or_id, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(stk_path.read_bytes())
        return destination
    file_acq.acquire_file = AsyncMock(side_effect=fake_acquire)

    await handle_media_upload(
        message=msg,
        state=fsm_ctx,
        settings=test_settings,
        job_manager=test_job_manager,
        repository=test_repo,
        rate_limiter=test_rate_limiter,
        file_acquisition=file_acq,
    )

    msg.answer.assert_called_once()
    text = msg.answer.call_args[0][0]
    assert "• Source: Telegram Sticker" in text
    assert "512×512" in text
    assert "WEBP" in text

    # Check job exists and metadata is correct
    assert test_job_manager.get_active_jobs_count() == 1
    job = list(test_job_manager.active_jobs.values())[0]
    assert job.metadata["is_sticker"] is True
    assert job.status == "ready"


@pytest.mark.asyncio
async def test_photo_and_document_upload(
    fsm_ctx,
    test_settings,
    test_job_manager,
    test_repo: DatabaseRepository,
    test_rate_limiter,
    mock_file_acquisition,
):
    # 1. Photo upload
    msg_photo = MagicMock()
    msg_photo.from_user.id = 2001
    msg_photo.from_user.username = "photouser"
    msg_photo.from_user.first_name = "Photo"
    msg_photo.from_user.last_name = None
    msg_photo.chat.id = 2001
    msg_photo.sticker = None
    msg_photo.document = None
    msg_photo.photo = [
        MagicMock(file_id="p1", file_unique_id="u1", file_size=500),
        MagicMock(file_id="p2", file_unique_id="u2", file_size=1500),
    ]
    msg_photo.answer = AsyncMock()

    await handle_media_upload(
        message=msg_photo,
        state=fsm_ctx,
        settings=test_settings,
        job_manager=test_job_manager,
        repository=test_repo,
        rate_limiter=test_rate_limiter,
        file_acquisition=mock_file_acquisition,
    )

    msg_photo.answer.assert_called_once()
    assert "Image Details" in msg_photo.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_callback_ownership_security(test_job_manager, test_settings):
    job = test_job_manager.create_job(user_id=1001, original_filename="photo.png")
    job.status = "ready"

    queue_mgr = MagicMock(spec=QueueManager)

    cb = MagicMock()
    cb.data = f"conv:{job.uuid}:webp"
    cb.from_user.id = 9999  # Different user!
    cb.answer = AsyncMock()

    await callback_convert_format(
        callback=cb,
        settings=test_settings,
        job_manager=test_job_manager,
        queue_manager=queue_mgr,
    )

    cb.answer.assert_called_once()
    assert "belongs to another user" in cb.answer.call_args[0][0]
    queue_mgr.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_callback_prevention(test_job_manager, test_settings):
    job = test_job_manager.create_job(user_id=1001, original_filename="photo.png")
    job.status = "processing"  # Already processing!

    queue_mgr = MagicMock(spec=QueueManager)

    cb = MagicMock()
    cb.data = f"conv:{job.uuid}:webp"
    cb.from_user.id = 1001
    cb.answer = AsyncMock()

    await callback_convert_format(
        callback=cb,
        settings=test_settings,
        job_manager=test_job_manager,
        queue_manager=queue_mgr,
    )

    cb.answer.assert_called_once()
    assert "already in progress" in cb.answer.call_args[0][0]
    queue_mgr.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_callback_cancel(test_job_manager, test_settings):
    job = test_job_manager.create_job(user_id=1001, original_filename="photo.png")
    job.status = "ready"

    queue_mgr = MagicMock(spec=QueueManager)

    cb = MagicMock()
    cb.data = f"conv:{job.uuid}:cancel"
    cb.from_user.id = 1001
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()

    await callback_convert_format(
        callback=cb,
        settings=test_settings,
        job_manager=test_job_manager,
        queue_manager=queue_mgr,
    )

    cb.answer.assert_called_once_with("Cancelled")
    cb.message.edit_text.assert_called_once()
    assert "cancelled" in cb.message.edit_text.call_args[0][0].lower()
    # Job removed
    assert test_job_manager.get_job(job.uuid) is None


@pytest.mark.asyncio
async def test_command_cancel(fsm_ctx, test_job_manager):
    job = test_job_manager.create_job(user_id=1001, original_filename="photo.png")

    msg = MagicMock()
    msg.from_user.id = 1001
    msg.answer = AsyncMock()

    await cmd_cancel(message=msg, state=fsm_ctx, job_manager=test_job_manager)

    msg.answer.assert_called_once()
    assert "cancelled" in msg.answer.call_args[0][0].lower()
    assert test_job_manager.get_job(job.uuid) is None


@pytest.mark.asyncio
async def test_conversion_worker_execution_and_delivery(
    sample_png: Path,
    test_job_manager: JobManager,
    test_settings: Settings,
):
    # Setup job with actual image
    job = test_job_manager.create_job(user_id=1001, original_filename="my_photo.png")
    job.original_path.write_bytes(sample_png.read_bytes())
    job.metadata["inspection"] = {"width": 200, "height": 200}
    job.status = "ready"
    job_uuid = job.uuid
    workspace_dir = job.workspace_dir

    queue_mgr = QueueManager(max_concurrent_jobs=1)
    queue_mgr.start()

    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()
    mock_bot.send_document = AsyncMock()
    mock_bot.delete_message = AsyncMock()
    mock_bot.edit_message_text = AsyncMock()

    cb = MagicMock()
    cb.data = f"conv:{job_uuid}:webp"
    cb.from_user.id = 1001
    cb.bot = mock_bot
    cb.message = MagicMock()
    cb.message.message_id = 42
    cb.message.chat.id = 1001
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()

    try:
        await callback_convert_format(
            callback=cb,
            settings=test_settings,
            job_manager=test_job_manager,
            queue_manager=queue_mgr,
        )

        cb.message.edit_text.assert_called_once()
        assert "Converting to WEBP" in cb.message.edit_text.call_args[0][0]

        # Wait for worker to finish processing
        for _ in range(50):
            if test_job_manager.get_job(job_uuid) is None:
                break
            await asyncio.sleep(0.1)

        # Verify preview was sent
        mock_bot.send_photo.assert_called_once()
        # Verify document was sent
        mock_bot.send_document.assert_called_once()
        doc_kwargs = mock_bot.send_document.call_args[1]
        assert "Converted to WEBP" in doc_kwargs["caption"]
        assert doc_kwargs["document"].filename == "my_photo.webp"

        # Verify cleanup of temporary workspace
        assert not workspace_dir.exists()

    finally:
        await queue_mgr.stop()
