from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def reminder_keyboard(task_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏱ Отложить", callback_data=f"remind:snooze:{task_id}"),
        InlineKeyboardButton(text="▶️ Взять в работу", callback_data=f"remind:take:{task_id}"),
        InlineKeyboardButton(text="✅ Готово", callback_data=f"remind:done:{task_id}"),
    )
    return builder.as_markup()
