from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def escalation_keyboard(task_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬆️ Повысить приоритет", callback_data=f"escalate:priority:{task_id}"),
        InlineKeyboardButton(text="👤 Переназначить", callback_data=f"escalate:reassign:{task_id}"),
        InlineKeyboardButton(text="Оставить как есть", callback_data=f"escalate:ignore:{task_id}"),
    )
    return builder.as_markup()
