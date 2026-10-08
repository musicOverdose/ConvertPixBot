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
    """Format selection inline keyboard for static image conversion."""
    buttons = [
        [
            InlineKeyboardButton(text='🖼 PNG', callback_data=f'conv:{job_uuid}:png'),
            InlineKeyboardButton(text='📸 JPG', callback_data=f'conv:{job_uuid}:jpg'),
            InlineKeyboardButton(text='🌐 WEBP', callback_data=f'conv:{job_uuid}:webp'),
        ],
        [
            InlineKeyboardButton(text='📄 PDF', callback_data=f'conv:{job_uuid}:pdf'),
            InlineKeyboardButton(text='🔲 ICO', callback_data=f'conv:{job_uuid}:ico'),
            InlineKeyboardButton(text='🎨 BMP', callback_data=f'conv:{job_uuid}:bmp'),
        ],
        [
            InlineKeyboardButton(text='❌ Cancel', callback_data=f'conv:{job_uuid}:cancel'),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
