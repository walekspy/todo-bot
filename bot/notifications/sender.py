import hashlib
from aiogram import Bot
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.config import Config
from bot.db.models import Task, Priority
from bot.keyboards.reminder import reminder_keyboard
from bot.keyboards.escalation import escalation_keyboard
from bot.llm.doc_analyzer import DocEvent

PRIORITY_EMOJI = {Priority.LOW: "🔵", Priority.MEDIUM: "🟡", Priority.HIGH: "🔴"}


async def send_task_reminder(bot: Bot, task: Task, config: Config) -> None:
    emoji = PRIORITY_EMOJI.get(task.priority, "🟡")
    text = f"🔔 <b>Напоминание</b>\n\n{emoji} {task.title}"
    if task.notes:
        text += f"\n<i>{task.notes}</i>"
    if task.assignee_username:
        text += f"\n👤 @{task.assignee_username}"

    # Telegram DM chat_ids are positive, groups are negative.
    # Escalation menu (priority/reassign) only makes sense in group chats.
    target_chat_id = task.notify_chat_id or task.chat_id
    is_private = target_chat_id > 0

    if task.snooze_count >= config.escalation_snooze_count and not is_private:
        markup = escalation_keyboard(task.id)
        text += f"\n\n⚠️ Задача откладывалась {task.snooze_count} раз. Изменить?"
    else:
        markup = reminder_keyboard(task.id)

    await bot.send_message(
        chat_id=target_chat_id,
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
    text = (
        f"📅 <b>Приближается дата</b>\n\n"
        f"<b>{event.title}</b> — {event.date.strftime('%d.%m.%Y')}"
    )
    if event.notes:
        text += f"\n<i>{event.notes}</i>"
    text += "\n\nСоздать задачу?"

    # Use a short hash of title+date to keep callback_data well within 64 bytes
    event_key = hashlib.sha1(f"{event.title}:{event.date.isoformat()}".encode()).hexdigest()[:12]

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Создать задачу",
            callback_data=f"event:create:{event.date.isoformat()}:{event_key}",
        ),
        InlineKeyboardButton(text="❌ Пропустить", callback_data="event:skip"),
    )

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
