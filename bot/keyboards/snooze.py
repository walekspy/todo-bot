from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.config import Config


def snooze_keyboard(task_id: str, config: Config) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="+1 час", callback_data=f"snooze:1h:{task_id}"),
        InlineKeyboardButton(text="+3 часа", callback_data=f"snooze:3h:{task_id}"),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"Вечером ({config.snooze_evening_hour}:00)",
            callback_data=f"snooze:evening:{task_id}",
        ),
        InlineKeyboardButton(
            text=f"Утром ({config.snooze_morning_hour}:00)",
            callback_data=f"snooze:morning:{task_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Другое время", callback_data=f"snooze:custom:{task_id}"),
    )
    return builder.as_markup()


def escalation_keyboard(task_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬆️ Повысить приоритет", callback_data=f"escalate:priority:{task_id}"),
        InlineKeyboardButton(text="👤 Переназначить", callback_data=f"escalate:reassign:{task_id}"),
        InlineKeyboardButton(text="Оставить как есть", callback_data=f"escalate:ignore:{task_id}"),
    )
    return builder.as_markup()
