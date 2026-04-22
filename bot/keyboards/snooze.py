from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.config import Config


def snooze_keyboard(task_id: str, config: Config = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="+15 мин", callback_data=f"snooze:15m:{task_id}"),
        InlineKeyboardButton(text="+30 мин", callback_data=f"snooze:30m:{task_id}"),
        InlineKeyboardButton(text="+1 час",  callback_data=f"snooze:1h:{task_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="Позже",        callback_data=f"snooze:later:{task_id}"),
        InlineKeyboardButton(text="✏️ Своё время", callback_data=f"snooze:custom:{task_id}"),
    )
    return builder.as_markup()
