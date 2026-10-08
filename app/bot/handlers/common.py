"""Common bot command handlers (/start, /help, /cancel, must_join_verify)."""

from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.must_join_menu import get_must_join_keyboard
from app.services.job_manager import JobManager
from app.services.message_service import MessageService, DEFAULT_WELCOME_MESSAGE, DEFAULT_HELP_MESSAGE
from app.services.must_join_service import MustJoinService

router = Router(name='common_router')


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    message_service: Optional[MessageService] = None,
) -> None:
    await state.clear()
    if message_service:
        welcome_text = await message_service.get_welcome_message(message.from_user)
    else:
        welcome_text = MessageService.render_template(DEFAULT_WELCOME_MESSAGE, message.from_user)
    await message.answer(welcome_text, parse_mode='HTML')


@router.message(Command('help'))
async def cmd_help(
    message: Message,
    message_service: Optional[MessageService] = None,
) -> None:
    if message_service:
        help_text = await message_service.get_help_message(message.from_user)
    else:
        help_text = MessageService.render_template(DEFAULT_HELP_MESSAGE, message.from_user)
    await message.answer(help_text, parse_mode='HTML')


@router.message(Command('cancel'))
async def cmd_cancel(message: Message, state: FSMContext, job_manager: JobManager) -> None:
    await state.clear()
    user_job = job_manager.get_user_active_job(message.from_user.id)
    if user_job:
        user_job.status = 'cancelled'
        job_manager.cleanup_job(user_job.uuid)
        await message.answer('❌ Active session cancelled. Temporary files deleted.')
    else:
        await message.answer('ℹ️ No active session to cancel.')


@router.callback_query(F.data == 'must_join_verify')
async def callback_must_join_verify(
    callback: CallbackQuery,
    must_join_service: MustJoinService,
    message_service: Optional[MessageService] = None,
) -> None:
    bot = callback.bot
    user = callback.from_user
    has_joined, missing = await must_join_service.check_user_membership(bot, user.id)

    if has_joined:
        await callback.answer('✅ Thank you! Membership confirmed.', show_alert=True)
        if message_service:
            welcome_text = await message_service.get_welcome_message(user)
        else:
            welcome_text = MessageService.render_template(DEFAULT_WELCOME_MESSAGE, user)
        text = "✅ <b>Membership Verified!</b>\n\n" + welcome_text

        if callback.message:
            await callback.message.edit_text(text, parse_mode='HTML')
    else:
        await callback.answer('⚠️ You have not joined all required channels yet.', show_alert=True)
        if callback.message:
            kb = get_must_join_keyboard(missing)
            await callback.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data == 'help_guide')
async def callback_help_guide(callback: CallbackQuery, message_service: Optional[MessageService] = None):
    if message_service:
        help_text = await message_service.get_help_message(callback.from_user)
    else:
        help_text = MessageService.render_template(DEFAULT_HELP_MESSAGE, callback.from_user)
    await callback.message.answer(help_text, parse_mode='HTML')
    await callback.answer()


@router.callback_query(F.data == 'bot_status')
async def callback_bot_status(callback: CallbackQuery, job_manager: JobManager):
    active_count = len(job_manager.active_jobs)
    await callback.answer('🟢 Bot is Online\nActive jobs: ' + str(active_count), show_alert=True)

