"""Main menu and interaction keyboards."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_start_keyboard() -> InlineKeyboardMarkup:
    """Default inline keyboard for /start welcome message."""
    buttons = [
        [
            InlineKeyboardButton(text='ℹ️ Help & Guide', callback_data='help_guide'),
            InlineKeyboardButton(text='⚙️ Status', callback_data='bot_status'),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_format_selection_keyboard(job_uuid: str) -> InlineKeyboardMarkup:
    """Example conversion format selection buttons."""
    buttons = [
        [
            InlineKeyboardButton(text='🖼 PNG', callback_data=f'conv:{job_uuid}:png'),
            InlineKeyboardButton(text='📸 JPEG', callback_data=f'conv:{job_uuid}:jpeg'),
            InlineKeyboardButton(text='🌐 WEBP', callback_data=f'conv:{job_uuid}:webp'),
        ],
        [
            InlineKeyboardButton(text='❌ Cancel', callback_data=f'conv:{job_uuid}:cancel'),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
