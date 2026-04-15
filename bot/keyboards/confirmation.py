from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def confirm_keyboard(task_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Сохранить", callback_data=f"confirm:save:{task_id}"),
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"confirm:edit:{task_id}"),
        InlineKeyboardButton(text="❌ Пропустить", callback_data=f"confirm:skip:{task_id}"),
    )
    return builder.as_markup()
