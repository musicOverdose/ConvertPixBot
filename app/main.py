"""Main application entrypoint: initializes dependencies, registers routers, and starts polling."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import admin_handlers, common, job_handler
from app.bot.middleware.must_join_middleware import MustJoinMiddleware
from app.config import get_settings
from app.database.connection import Database
from app.database.repository import DatabaseRepository
from app.services.broadcast_service import BroadcastService
from app.services.file_acquisition import FileAcquisitionService
from app.services.job_manager import JobManager
from app.services.message_service import MessageService
from app.services.must_join_service import MustJoinService
from app.services.queue_manager import QueueManager
from app.services.rate_limiter import RateLimiter

logger = logging.getLogger('bot_app')


async def periodic_cleanup_task(job_manager: JobManager, interval_seconds: int = 300):
    """Periodically cleans up abandoned jobs."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            cleaned = job_manager.cleanup_expired_jobs()
            if cleaned > 0:
                logger.info(f'Periodic GC: cleaned {cleaned} abandoned jobs.')
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f'Error in periodic cleanup task: {e}')


async def main():
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout,
    )

    if not settings.bot_token:
        logger.error('BOT_TOKEN is not set! Please configure it in your environment or .env file.')
        sys.exit(1)

    logger.info(f'Initializing {settings.bot_name}...')

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Database & Services
    db = Database(settings.db_path)
    await db.connect()
    repository = DatabaseRepository(db)

    job_manager = JobManager(
        base_jobs_dir=settings.jobs_dir,
        ttl_minutes=settings.job_ttl_minutes,
        max_user_concurrent_jobs=settings.max_user_concurrent_jobs,
        max_global_concurrent_jobs=settings.max_global_concurrent_jobs,
    )
    job_manager.cleanup_orphaned_job_dirs()

    queue_manager = QueueManager(max_concurrent_jobs=settings.max_concurrent_jobs)
    queue_manager.start()

    must_join_service = MustJoinService(repository)
    message_service = MessageService(repository)
    file_acquisition = FileAcquisitionService(settings)
    rate_limiter = RateLimiter(
        max_requests=settings.rate_limit_uploads_per_minute,
        window_seconds=60,
    )
    broadcast_service = BroadcastService(repository)

    # Configure Telegram Session
    session = None
    if settings.is_local_mode:
        custom_server = TelegramAPIServer.from_base(
            settings.effective_api_base_url,
            is_local=False,
        )
        session = AiohttpSession(api=custom_server)
        logger.info(
            f'Bot operating in LOCAL MODE with API server: {settings.effective_api_base_url}'
        )
    else:
        logger.info('Bot operating in CLOUD MODE (https://api.telegram.org)')

    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Dependency Injection
    dp['bot'] = bot
    dp['settings'] = settings
    dp['repository'] = repository
    dp['job_manager'] = job_manager
    dp['queue_manager'] = queue_manager
    dp['must_join_service'] = must_join_service
    dp['message_service'] = message_service
    dp['file_acquisition'] = file_acquisition
    dp['rate_limiter'] = rate_limiter
    dp['broadcast_service'] = broadcast_service

    # Middleware
    dp.message.middleware(MustJoinMiddleware(must_join_service, message_service))
    dp.callback_query.middleware(MustJoinMiddleware(must_join_service, message_service))

    # Routers
    dp.include_router(common.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(job_handler.router)

    cleanup_task = asyncio.create_task(periodic_cleanup_task(job_manager))

    try:
        logger.info('Starting bot polling...')
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        cleanup_task.cancel()
        await queue_manager.stop()
        if bot.session:
            await bot.session.close()
        await db.close()
        logger.info('Bot stopped gracefully.')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
