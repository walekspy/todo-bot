from aiogram import Bot
from bot.config import Config
from bot.db.models import Task, Priority
from bot.keyboards.reminder import reminder_keyboard
from bot.llm.doc_analyzer import DocEvent

PRIORITY_EMOJI = {Priority.LOW: "🔵", Priority.MEDIUM: "🟡", Priority.HIGH: "🔴"}


async def send_task_reminder(bot: Bot, task: Task, config: Config) -> None:
    emoji = PRIORITY_EMOJI.get(task.priority, "🟡")
    text = f"🔔 <b>Напоминание</b>\n\n{emoji} {task.title}"
    if task.notes:
        text += f"\n<i>{task.notes}</i>"

    if task.snooze_count >= config.escalation_snooze_count:
        from bot.keyboards.snooze import escalation_keyboard
        markup = escalation_keyboard(task.id)
        text += f"\n\n⚠️ Задача откладывалась {task.snooze_count} раз. Изменить?"
    else:
        markup = reminder_keyboard(task.id)

    await bot.send_message(
        chat_id=task.chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=markup,
    )


async def send_event_alert(
    bot: Bot,
    chat_id: int,
    event: DocEvent,
    config: Config,
) -> None:
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    text = (
        f"📅 <b>Приближается дата</b>\n\n"
        f"<b>{event.title}</b> — {event.date.strftime('%d.%m.%Y')}"
    )
    if event.notes:
        text += f"\n<i>{event.notes}</i>"
    text += "\n\nСоздать задачу?"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Создать задачу",
            callback_data=f"event:create:{event.date.isoformat()}:{event.title[:20]}",
        ),
        InlineKeyboardButton(text="❌ Пропустить", callback_data="event:skip"),
    )

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
