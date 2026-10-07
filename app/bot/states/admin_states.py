"""FSM States for Admin Panel interactions."""

from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_for_channel_input = State()
    waiting_for_whitelist_input = State()
    waiting_for_ban_input = State()
    waiting_for_broadcast_content = State()
    waiting_for_broadcast_confirm = State()
    waiting_for_local_url = State()
    waiting_for_custom_input_mb = State()
    waiting_for_custom_output_mb = State()
    waiting_for_custom_message = State()
