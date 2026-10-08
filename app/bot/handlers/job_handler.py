"""Media / Job processing handler: queueing, file acquisition, conversion & delivery."""

import asyncio
import logging
from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.config import Settings
from app.database.repository import DatabaseRepository
from app.engine.processor import (
    MediaProcessor,
    UnsupportedFormatError,
    CorruptedImageError,
    ImageDimensionLimitError,
)
from app.bot.formatting import (
    format_image_details,
    format_conversion_caption,
    sanitize_filename,
)
from app.bot.keyboards.main_menu import get_format_selection_keyboard
from app.services.file_acquisition import FileAcquisitionService
from app.services.job_manager import JobManager
from app.services.queue_manager import QueueManager
from app.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

router = Router(name='job_handler_router')


@router.message(F.photo | F.document | F.sticker)
async def handle_media_upload(
    message: Message,
    state: FSMContext,
    settings: Settings,
    job_manager: JobManager,
    repository: DatabaseRepository,
    rate_limiter: RateLimiter,
    file_acquisition: FileAcquisitionService,
) -> None:
    """Accepts user photo, document, or static sticker, acquires it, inspects it, and presents conversion options."""
    user = message.from_user
    if not user:
        return

    # Check rate limit
    if not settings.is_admin(user.id) and not await repository.is_whitelisted(user.id):
        allowed, retry = rate_limiter.check(user.id)
        if not allowed:
            await message.answer(f'⏳ Rate limited! Please wait {retry}s before uploading another file.')
            return

    # Determine input type & validate stickers
    is_sticker = False
    if message.sticker:
        sticker = message.sticker
        if sticker.is_animated or sticker.is_video:
            await message.answer(
                '❌ Animated and video stickers are not supported.\n\n'
                'Please send a static sticker or image.'
            )
            return
        is_sticker = True
        file_id = sticker.file_id
        file_size = sticker.file_size or 0
        file_name = f'sticker_{sticker.file_unique_id}.webp'

    elif message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_size = photo.file_size or 0
        file_name = f'photo_{photo.file_unique_id}.jpg'

    else:
        doc = message.document
        if not doc:
            return
        file_id = doc.file_id
        file_size = doc.file_size or 0
        raw_name = doc.file_name or f'doc_{doc.file_unique_id}.png'
        file_name = sanitize_filename(raw_name, fallback=f'doc_{doc.file_unique_id}.png')

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
            chat_id=message.chat.id,
        )
    except Exception as e:
        logger.warning(f'Could not create job for user {user.id}: {e}')
        await message.answer(f'⚠️ Unable to create processing job: {e}')
        return

    # Download and acquire the file into the isolated workspace
    try:
        await file_acquisition.acquire_file(
            bot=message.bot,
            file_or_id=file_id,
            destination=job.original_path,
        )
    except Exception as e:
        logger.exception(f'Failed to acquire file for job {job.uuid}: {e}')
        job_manager.cleanup_job(job.uuid)
        await message.answer('❌ Failed to download file from Telegram. Please try again.')
        return

    # Inspect the acquired file with Pillow
    try:
        inspection = await MediaProcessor.async_inspect_image(job.original_path)
    except UnsupportedFormatError:
        job_manager.cleanup_job(job.uuid)
        await message.answer(
            '❌ Unsupported image format.\n\n'
            'Supported formats: PNG, JPG, WEBP, BMP, ICO, HEIC, AVIF, PSD.'
        )
        return
    except ImageDimensionLimitError:
        job_manager.cleanup_job(job.uuid)
        await message.answer('❌ Image dimensions or pixel count exceed maximum safe limit.')
        return
    except CorruptedImageError:
        job_manager.cleanup_job(job.uuid)
        await message.answer('❌ Unsupported or corrupted image file.')
        return
    except Exception as e:
        logger.exception(f'Inspection error on job {job.uuid}: {e}')
        job_manager.cleanup_job(job.uuid)
        await message.answer('❌ Failed to inspect image file.')
        return

    # Update job state and metadata
    job.status = 'ready'
    job.metadata['telegram_file_id'] = file_id
    job.metadata['is_sticker'] = is_sticker
    job.metadata['inspection'] = inspection
    job.metadata['display_name'] = file_name

    # Record user in repository
    await repository.record_user_activity(user_id=user.id)

    # Display image information and target format keyboard
    details_text = format_image_details(
        filename=file_name,
        format_name=inspection['format'],
        width=inspection['width'],
        height=inspection['height'],
        file_size_bytes=inspection['file_size_bytes'],
        color_mode=inspection['mode'],
        is_sticker=is_sticker,
    )

    await message.answer(
        details_text,
        parse_mode='HTML',
        reply_markup=get_format_selection_keyboard(job.uuid),
    )


@router.callback_query(F.data.startswith('conv:'))
async def callback_convert_format(
    callback: CallbackQuery,
    settings: Settings,
    job_manager: JobManager,
    queue_manager: QueueManager,
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

    # Callback security: ownership check
    if job.user_id != callback.from_user.id:
        await callback.answer('Unauthorized: this session belongs to another user.', show_alert=True)
        return

    # Cancellation handling
    if target_fmt == 'cancel':
        job.status = 'cancelled'
        job_manager.cleanup_job(job_uuid)
        if callback.message:
            await callback.message.edit_text('❌ Conversion cancelled.')
        await callback.answer('Cancelled')
        return

    # Prevent duplicate taps
    if job.status in ('queued', 'processing', 'completed'):
        await callback.answer('Conversion is already in progress.', show_alert=False)
        return
    if job.status == 'cancelled':
        await callback.answer('This session was cancelled.', show_alert=False)
        return

    # Immediately lock job and update UI to prevent duplicates
    job.status = 'queued'
    fmt_upper = target_fmt.upper()
    if callback.message:
        await callback.message.edit_text(f'⚙️ Converting to {fmt_upper}...', reply_markup=None)
    await callback.answer()

    status_msg_id = callback.message.message_id if callback.message else 0
    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    bot: Bot = callback.bot

    # Worker conversion coroutine
    async def run_conversion_job() -> None:
        current_job = job_manager.get_job(job_uuid)
        if not current_job or current_job.status == 'cancelled':
            return

        current_job.status = 'processing'
        try:
            orig_stem = Path(current_job.original_filename).stem
            out_ext = target_fmt.lower()
            output_filename = f'{orig_stem}.{out_ext}'
            output_path = current_job.workspace_dir / f'out_{current_job.uuid[:8]}.{out_ext}'

            # 1. Convert image via MediaProcessor
            await MediaProcessor.convert_image(
                input_path=current_job.original_path,
                output_format=target_fmt,
                target_path=output_path,
            )

            # 2. Validate converted output
            MediaProcessor.validate_output(output_path, target_fmt)

            if current_job.status == 'cancelled':
                return

            # 3. Generate preview (from output_path for images, or original_path for PDF)
            preview_path = current_job.workspace_dir / f'preview_{current_job.uuid[:8]}.jpg'
            preview_source = current_job.original_path if target_fmt.lower() == 'pdf' else output_path
            has_preview = False
            try:
                await MediaProcessor.generate_preview(
                    source_path=preview_source,
                    preview_path=preview_path,
                )
                has_preview = preview_path.exists() and preview_path.stat().st_size > 0
            except Exception as prev_err:
                logger.warning(f'Preview generation skipped for job {job_uuid}: {prev_err}')

            if current_job.status == 'cancelled':
                return

            # 4. Calculate output statistics and caption
            in_bytes = current_job.original_path.stat().st_size
            out_bytes = output_path.stat().st_size
            inspection = current_job.metadata.get('inspection', {})
            width = inspection.get('width', 0)
            height = inspection.get('height', 0)
            if target_fmt.lower() != 'pdf':
                try:
                    out_info = MediaProcessor.inspect_image(output_path)
                    width = out_info.get('width', width)
                    height = out_info.get('height', height)
                except Exception:
                    pass

            caption = format_conversion_caption(
                target_format=target_fmt,
                width=width,
                height=height,
                out_size_bytes=out_bytes,
                in_size_bytes=in_bytes,
            )

            # 5. Deliver result: Visual Preview first (convenience only)
            if has_preview:
                try:
                    preview_file = FSInputFile(path=str(preview_path), filename='preview.jpg')
                    await bot.send_photo(chat_id=chat_id, photo=preview_file)
                except Exception as e:
                    logger.warning(f'Could not send visual preview for job {job_uuid}: {e}')

            if current_job.status == 'cancelled':
                return

            # 6. Deliver result: Authoritative uncompressed exact Document
            doc_file = FSInputFile(path=str(output_path), filename=output_filename)
            await bot.send_document(
                chat_id=chat_id,
                document=doc_file,
                caption=caption,
            )

            current_job.status = 'completed'

            # Remove temporary progress message
            if status_msg_id:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
                except Exception:
                    pass

        except Exception as e:
            logger.exception(f'Conversion failed for job {job_uuid}: {e}')
            if status_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=(
                            '❌ Conversion failed.\n\n'
                            'The image could not be converted to this format.'
                        ),
                    )
                except Exception:
                    pass
        finally:
            job_manager.cleanup_job(job_uuid)

    # Queue background task
    await queue_manager.enqueue(
        job_id=job.uuid,
        user_id=callback.from_user.id,
        task_func=run_conversion_job,
    )
