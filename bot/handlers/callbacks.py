from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery
from bot.config import Config
from bot.db.models import Task, TaskStatus, Priority
from bot.db.repository import TaskRepo
from bot.keyboards.snooze import snooze_keyboard
from bot.keyboards.reminder import reminder_keyboard


def setup_callbacks_router(
    task_repo: TaskRepo,
    config: Config,
    pending_tasks: dict,
) -> Router:
    router = Router()

    # ── helpers ────────────────────────────────────────────────────────

    async def _check_assignee(callback: CallbackQuery, task: Task) -> bool:
        """Return True if caller is allowed to action this task. Show alert otherwise."""
        if task.assignee_id and callback.from_user.id != task.assignee_id:
            await callback.answer(
                "Эта задача назначена другому участнику.", show_alert=True
            )
            return False
        return True

    # ── Confirmation callbacks ──────────────────────────────────────────

    @router.callback_query(F.data.startswith("confirm:save:"))
    async def on_confirm_save(callback: CallbackQuery) -> None:
        tmp_id = callback.data.split(":", 2)[2]
        raw = pending_tasks.pop(tmp_id, None)
        if raw is None:
            await callback.answer("Задача уже обработана.")
            return
        task = Task(
            title=raw.title,
            notes=raw.notes,
            priority=raw.priority,
            source=raw.source,
            source_ref=raw.source_ref,
            due_at=raw.due_at,
            remind_at=raw.remind_at or datetime.now(timezone.utc) + timedelta(hours=1),
            recurrence=raw.recurrence,
            owner_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
        )
        await task_repo.save(task)
        await callback.message.edit_text(
            f"✅ Задача сохранена: <b>{task.title}</b>", parse_mode="HTML"
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("confirm:skip:"))
    async def on_confirm_skip(callback: CallbackQuery) -> None:
        tmp_id = callback.data.split(":", 2)[2]
        pending_tasks.pop(tmp_id, None)
        await callback.message.edit_text("❌ Задача пропущена.")
        await callback.answer()

    # ── Reminder callbacks ──────────────────────────────────────────────

    @router.callback_query(F.data.startswith("remind:done:"))
    async def on_remind_done(callback: CallbackQuery) -> None:
        task_id = callback.data.split(":", 2)[2]
        task = await task_repo.get(task_id)
        if task is None:
            await callback.answer("Задача не найдена.")
            return
        if not await _check_assignee(callback, task):
            return
        await task_repo.update_status(task_id, TaskStatus.DONE)
        name = callback.from_user.username or callback.from_user.first_name
        text = f"✅ Выполнено: <b>{task.title}</b>"
        if callback.message.chat.type != "private":
            text += f" — @{name}"
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Отмечено как выполненное!")

    @router.callback_query(F.data.startswith("remind:take:"))
    async def on_remind_take(callback: CallbackQuery) -> None:
        task_id = callback.data.split(":", 2)[2]
        task = await task_repo.get(task_id)
        if task is None:
            await callback.answer("Задача не найдена.")
            return
        if not await _check_assignee(callback, task):
            return
        await task_repo.update_status(task_id, TaskStatus.ACTIVE)
        await callback.message.edit_text(
            f"▶️ Взято в работу: <b>{task.title}</b>\nПроверю через 30 минут.",
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("remind:snooze:"))
    async def on_remind_snooze(callback: CallbackQuery) -> None:
        task_id = callback.data.split(":", 2)[2]
        task = await task_repo.get(task_id)
        if task is None:
            await callback.answer("Задача не найдена.")
            return
        if not await _check_assignee(callback, task):
            return
        await callback.message.edit_reply_markup(
            reply_markup=snooze_keyboard(task_id, config)
        )
        await callback.answer()

    # ── Snooze time selection ───────────────────────────────────────────

    @router.callback_query(F.data.startswith("snooze:"))
    async def on_snooze_choice(callback: CallbackQuery) -> None:
        parts = callback.data.split(":", 2)
        option = parts[1]
        task_id = parts[2]

        now = datetime.now(timezone.utc)

        if option == "1h":
            until = now + timedelta(hours=1)
        elif option == "3h":
            until = now + timedelta(hours=3)
        elif option == "evening":
            until = now.replace(
                hour=config.snooze_evening_hour, minute=0, second=0, microsecond=0
            )
            if until <= now:
                until += timedelta(days=1)
        elif option == "morning":
            until = (now + timedelta(days=1)).replace(
                hour=config.snooze_morning_hour, minute=0, second=0, microsecond=0
            )
        elif option == "custom":
            await callback.message.reply(
                "Напиши время для напоминания в формате:\n"
                "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code> или просто <code>ЧЧ:ММ</code> (сегодня)",
                parse_mode="HTML",
            )
            await callback.answer()
            return
        else:
            await callback.answer("Неизвестный вариант.")
            return

        await task_repo.snooze(task_id, until)
        task = await task_repo.get(task_id)
        await callback.message.edit_text(
            f"⏱ <b>{task.title}</b>\nОтложено до {until.strftime('%d.%m %H:%M')} UTC",
            parse_mode="HTML",
        )
        await callback.answer()

    # ── Escalation callbacks ────────────────────────────────────────────

    @router.callback_query(F.data.startswith("escalate:priority:"))
    async def on_escalate_priority(callback: CallbackQuery) -> None:
        task_id = callback.data.split(":", 2)[2]
        await task_repo.update_priority(task_id, Priority.HIGH)
        task = await task_repo.get(task_id)
        await callback.message.edit_text(
            f"🔴 Приоритет повышен: <b>{task.title}</b>",
            parse_mode="HTML",
            reply_markup=reminder_keyboard(task_id),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("escalate:reassign:"))
    async def on_escalate_reassign(callback: CallbackQuery) -> None:
        # TODO: Implement reassignment UI flow — requires listing family member user IDs
        # and presenting a selection keyboard. For now, prompt the user manually.
        await callback.message.reply(
            "Чтобы переназначить задачу, укажи участника командой:\n"
            "<code>/assign {task_id} @username</code>",
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("escalate:ignore:"))
    async def on_escalate_ignore(callback: CallbackQuery) -> None:
        task_id = callback.data.split(":", 2)[2]
        await callback.message.edit_reply_markup(
            reply_markup=reminder_keyboard(task_id)
        )
        await callback.answer()

    # ── Event alert callbacks ───────────────────────────────────────────

    @router.callback_query(F.data.startswith("event:create:"))
    async def on_event_create(callback: CallbackQuery) -> None:
        # Format: event:create:{YYYY-MM-DD}:{event_key}
        parts = callback.data.split(":", 3)
        date_str = parts[2] if len(parts) > 2 else ""
        # Parse the date for display; task creation is manual follow-up
        try:
            from datetime import date
            event_date = date.fromisoformat(date_str)
            remind_dt = datetime.combine(
                event_date, datetime.min.time()
            ).replace(tzinfo=timezone.utc).replace(
                hour=config.snooze_morning_hour
            )
        except (ValueError, IndexError):
            remind_dt = datetime.now(timezone.utc) + timedelta(days=1)

        # Prompt user to name the task
        await callback.message.edit_text(
            "✏️ Напиши название задачи для этого события, и я её сохраню.",
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data == "event:skip")
    async def on_event_skip(callback: CallbackQuery) -> None:
        await callback.message.edit_text("❌ Событие пропущено.")
        await callback.answer()

    return router
