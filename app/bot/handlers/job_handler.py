"""Media / Job processing handler: queueing, file acquisition, conversion & delivery."""

import asyncio
import logging
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.config import Settings
from app.database.repository import DatabaseRepository
from app.engine.processor import MediaProcessor
from app.bot.keyboards.main_menu import get_format_selection_keyboard
from app.services.file_acquisition import FileAcquisitionService
from app.services.job_manager import JobManager
from app.services.queue_manager import QueueManager
from app.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

router = Router(name='job_handler_router')


@router.message(F.photo | F.document)
async def handle_media_upload(
    message: Message,
    state: FSMContext,
    settings: Settings,
    job_manager: JobManager,
    repository: DatabaseRepository,
    rate_limiter: RateLimiter,
) -> None:
    """Accepts user file/photo and presents conversion options."""
    user = message.from_user
    if not user:
        return

    # Check rate limit
    if not settings.is_admin(user.id) and not await repository.is_whitelisted(user.id):
        allowed, retry = rate_limiter.check(user.id)
        if not allowed:
            await message.answer(f'⏳ Rate limited! Please wait {retry}s before uploading another file.')
            return

    # Determine file size & telegram file id
    if message.photo:
        tg_file = message.photo[-1]
        file_size = tg_file.file_size or 0
        file_id = tg_file.file_id
        file_name = f'image_{tg_file.file_unique_id}.jpg'
    else:
        doc = message.document
        file_size = doc.file_size or 0
        file_id = doc.file_id
        file_name = doc.file_name or f'doc_{doc.file_unique_id}'

    # Check size limits
    if file_size > settings.max_input_bytes:
        await message.answer(f'⚠️ File exceeds maximum allowed size of {settings.max_input_mb} MB.')
        return

    # Create job in JobManager
    try:
        job = job_manager.create_job(
            user_id=user.id,
            original_filename=file_name,
            file_size_bytes=file_size,
        )
    except Exception as e:
        await message.answer(f'⚠️ Unable to create processing job: {e}')
        return

    # Store file_id in job metadata
    job.metadata['telegram_file_id'] = file_id

    # Record or update user in database
    await repository.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

    await message.answer(
        f'📥 <b>Received:</b> <code>{file_name}</code>
'
        f'Select target format to convert:',
        parse_mode='HTML',
        reply_markup=get_format_selection_keyboard(job.uuid),
    )


@router.callback_query(F.data.startswith('conv:'))
async def callback_convert_format(
    callback: CallbackQuery,
    settings: Settings,
    job_manager: JobManager,
    queue_manager: QueueManager,
    file_acquisition: FileAcquisitionService,
) -> None:
    parts = callback.data.split(':')
    if len(parts) != 3:
        await callback.answer('Invalid action')
        return

    _, job_uuid, target_fmt = parts
    job = job_manager.get_job(job_uuid)
    if not job:
        await callback.answer('Job expired or not found.', show_alert=True)
        return

    if target_fmt == 'cancel':
        job_manager.cleanup_job(job_uuid)
        if callback.message:
            await callback.message.edit_text('❌ Conversion cancelled.')
        await callback.answer('Cancelled')
        return

    if callback.message:
        await callback.message.edit_text(f'⏳ Queued for conversion to <b>{target_fmt.upper()}</b>...', parse_mode='HTML')
    await callback.answer()

    # Define background worker task
    async def worker_task(worker_id: int):
        try:
            if callback.message:
                await callback.message.edit_text(f'⚡ Downloading file via API server...')

            # 1. Acquire file (local copy or HTTP download fallback)
            file_id = job.metadata.get('telegram_file_id')
            await file_acquisition.acquire_file(
                bot=callback.bot,
                file_id=file_id,
                destination=job.original_path,
            )

            if callback.message:
                await callback.message.edit_text(f'⚙️ Converting to {target_fmt.upper()}...')

            # 2. Convert using engine
            output_file = job.workspace_dir / f'converted_{job.uuid[:8]}.{target_fmt.lower()}'
            await MediaProcessor.convert_image(
                input_path=job.original_path,
                output_format=target_fmt,
                target_path=output_file,
            )

            # 3. Send result back to user
            if callback.message:
                await callback.message.edit_text(f'📤 Uploading converted file...')

            doc_to_send = FSInputFile(path=str(output_file), filename=output_file.name)
            await callback.bot.send_document(
                chat_id=callback.from_user.id,
                document=doc_to_send,
                caption=f'✅ Converted successfully to {target_fmt.upper()}',
            )

            if callback.message:
                await callback.message.delete()

        except Exception as e:
            logger.exception(f'Error processing job {job_uuid}: {e}')
            if callback.message:
                await callback.message.edit_text(f'❌ Failed to convert file: {e}')
        finally:
            # 4. Clean up temporary files
            job_manager.cleanup_job(job_uuid)

    # Dispatch to worker queue
    queue_manager.enqueue(
        job_uuid=job.uuid,
        user_id=callback.from_user.id,
        task_coro=worker_task,
    )
