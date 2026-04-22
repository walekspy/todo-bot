from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.db.models import Task


def done_list_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    """One row per task with Done + Snooze buttons."""
    builder = InlineKeyboardBuilder()
    for task in tasks:
        title = task.title if len(task.title) <= 28 else task.title[:25] + "…"
        builder.row(
            InlineKeyboardButton(
                text=f"✅ {title}",
                callback_data=f"done_list:{task.id}",
            ),
            InlineKeyboardButton(
                text="⏱",
                callback_data=f"list_snooze:{task.id}",
            ),
        )
    return builder.as_markup()
