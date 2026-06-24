from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from croniter import croniter
import logging
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.config import Config
from bot.db.models import Task, TaskStatus, Priority
from bot.db.repository import TaskRepo, ChatMemberRepo, ChatSettingsRepo
from bot.keyboards.snooze import snooze_keyboard
from bot.keyboards.reminder import reminder_keyboard
from bot.handlers.snooze_fsm import CustomSnoozeStates, WatchStates

logger = logging.getLogger(__name__)


def setup_callbacks_router(
    task_repo: TaskRepo,
    config: Config,
    pending_tasks: dict,
    scheduler: AsyncIOScheduler,
    bot: Bot,
    source_repo=None,
    llm_client=None,
    member_repo: ChatMemberRepo = None,
    settings_repo: ChatSettingsRepo = None,
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
        chat_id = callback.message.chat.id
        notify_chat_id = None
        if settings_repo:
            settings = await settings_repo.get(chat_id)
            if settings:
                notify_chat_id = settings.notify_chat_id
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
            chat_id=chat_id,
            assignee_username=getattr(raw, "assignee_username", None),
            notify_chat_id=notify_chat_id,
        )
        await task_repo.save(task)
        from bot.scheduler.jobs import task_reminder_job
        scheduler.add_job(
            task_reminder_job,
            trigger="date",
            run_date=task.remind_at,
            id=f"reminder_{task.id}",
            replace_existing=True,
            kwargs={
                "task_id": task.id,
                "bot": bot,
                "task_repo": task_repo,
                "config": config,
                "scheduler": scheduler,
            },
        )
        confirm_text = f"✅ Задача сохранена: <b>{task.title}</b>"
        if task.remind_at:
            local_dt = task.remind_at.astimezone(ZoneInfo(config.timezone))
            confirm_text += f"\n📅 {local_dt.strftime('%d.%m.%Y %H:%M')}"
        if task.recurrence:
            confirm_text += "\n🔄 Повторяется"
        await callback.message.edit_text(confirm_text, parse_mode="HTML")
        # In group chats without explicit assignee — suggest who to assign
        is_group = callback.message.chat.type in ("group", "supergroup")
        if is_group and not task.assignee_username and member_repo:
            members = await member_repo.list_for_chat(task.chat_id)
            if members:
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                from aiogram.types import InlineKeyboardButton
                builder = InlineKeyboardBuilder()
                for m in members:
                    label = f"@{m.username}" if m.username else m.first_name
                    value = m.username or str(m.user_id)
                    builder.button(text=label, callback_data=f"assign:{task.id}:{value}")
                builder.button(text="Без назначения", callback_data=f"assign:{task.id}:none")
                builder.adjust(2)
                await callback.message.answer(
                    "👤 Кому назначить задачу?",
                    reply_markup=builder.as_markup(),
                )
        await callback.answer()

    @router.callback_query(F.data.startswith("assign:"))
    async def on_assign(callback: CallbackQuery) -> None:
        parts = callback.data.split(":", 2)
        task_id, value = parts[1], parts[2]
        if value != "none":
            await task_repo.update_assignee_username(task_id, value)
            await callback.message.edit_text(f"👤 Назначено: @{value}")
        else:
            await callback.message.edit_text("👤 Без назначения.")
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

        # ── Recurring task: reschedule instead of closing ──
        if task.recurrence:
            try:
                tz = ZoneInfo(config.timezone)
                now = datetime.now(tz)
                # Use now as base so we don't skip a day when remind_at was
                # already advanced by the past-due logic.
                base = now
                cron = croniter(task.recurrence, base)
                next_dt = cron.get_next(datetime)
                # If next_dt is in the past (edge case: cron pattern matched
                # "now" again), advance until future
                while next_dt <= now:
                    next_dt = cron.get_next(datetime)
                next_utc = next_dt.astimezone(timezone.utc)
                await task_repo.reschedule(task_id, next_utc)
                from bot.scheduler.jobs import task_reminder_job
                scheduler.add_job(
                    task_reminder_job,
                    trigger="date",
                    run_date=next_utc,
                    id=f"reminder_{task.id}",
                    replace_existing=True,
                    kwargs={
                        "task_id": task.id,
                        "bot": bot,
                        "task_repo": task_repo,
                        "config": config,
                        "scheduler": scheduler,
                    },
                )
                local_str = next_dt.strftime("%d.%m.%Y %H:%M")
                text = f"✅ Выполнено: <b>{task.title}</b>\n🔄 Следующее: {local_str}"
                if callback.message.chat.type != "private":
                    name = callback.from_user.username or callback.from_user.first_name
                    text += f" — @{name}"
                await callback.message.edit_text(text, parse_mode="HTML")
                await callback.answer("Следующее запланировано!")
                return
            except Exception as e:
                logger.error("reschedule failed for %s: %s", task_id, e)
                # Fall through to normal DONE — don't lose the task
        # ── Non-recurring: mark done ──
        await task_repo.update_status(task_id, TaskStatus.DONE)
        name = callback.from_user.username or callback.from_user.first_name
        text = f"✅ Выполнено: <b>{task.title}</b>"
        if callback.message.chat.type != "private":
            text += f" — @{name}"
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Отмечено как выполненное!")

    @router.callback_query(F.data.startswith("remind:cancel:"))
    async def on_remind_cancel(callback: CallbackQuery) -> None:
        task_id = callback.data.split(":", 2)[2]
        task = await task_repo.get(task_id)
        if task is None:
            await callback.answer("Задача не найдена.")
            return
        if not await _check_assignee(callback, task):
            return
        await task_repo.update_status(task_id, TaskStatus.CANCELLED)
        name = callback.from_user.username or callback.from_user.first_name
        extra = ""
        if task.recurrence:
            extra = "\n🛑 Серия остановлена"
        text = f"❌ Отменено: <b>{task.title}</b>{extra}"
        if callback.message.chat.type != "private":
            text += f" — @{name}"
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Задача отменена")

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

    def _is_night(dt: datetime) -> bool:
        """Return True if dt falls within the configured night window."""
        h = dt.hour
        if config.night_start_hour > config.night_end_hour:
            # window wraps midnight: e.g. 23–7
            return h >= config.night_start_hour or h < config.night_end_hour
        return config.night_start_hour <= h < config.night_end_hour

    def _skip_night(dt: datetime) -> tuple:
        """If dt is in night window return (adjusted_dt, True), else (dt, False)."""
        if not _is_night(dt):
            return dt, False
        # advance to night_end_hour on the same or next day
        candidate = dt.replace(hour=config.night_end_hour, minute=0, second=0, microsecond=0)
        if candidate <= dt:
            candidate += timedelta(days=1)
        return candidate, True

    @router.callback_query(F.data.startswith("snooze:"))
    async def on_snooze_choice(callback: CallbackQuery, state: FSMContext) -> None:
        parts = callback.data.split(":", 2)
        option = parts[1]
        task_id = parts[2]

        tz = ZoneInfo(config.timezone)
        now_local = datetime.now(tz)
        warning = ""

        if option == "15m":
            until = now_local + timedelta(minutes=15)
        elif option == "30m":
            until = now_local + timedelta(minutes=30)
        elif option == "1h":
            until = now_local + timedelta(hours=1)
        elif option == "later":
            evening = now_local.replace(hour=22, minute=0, second=0, microsecond=0)
            if now_local >= evening:
                evening += timedelta(days=1)
            until = evening
        elif option == "tomorrow":
            until = (now_local + timedelta(days=1)).replace(
                hour=config.snooze_morning_hour, minute=0, second=0, microsecond=0
            )
        elif option == "custom":
            await state.set_state(CustomSnoozeStates.waiting_for_time)
            await state.update_data(task_id=task_id)
            await callback.message.reply(
                "Введи время напоминания:\n"
                "<code>15:30</code> — сегодня в 15:30\n"
                "<code>завтра в 10</code>\n"
                "<code>через 2 часа</code>\n"
                "<code>05.05 10:00</code>",
                parse_mode="HTML",
            )
            await callback.answer()
            return
        else:
            await callback.answer("Неизвестный вариант.")
            return

        await task_repo.snooze(task_id, until)
        from bot.scheduler.jobs import task_reminder_job
        scheduler.add_job(
            task_reminder_job,
            trigger="date",
            run_date=until,
            id=f"reminder_{task_id}",
            replace_existing=True,
            kwargs={
                "task_id": task_id,
                "bot": bot,
                "task_repo": task_repo,
                "config": config,
                "scheduler": scheduler,
            },
        )
        task = await task_repo.get(task_id)
        local_dt = until.astimezone(tz)
        local_str = f"{local_dt.strftime('%d.%m')} в {local_dt.strftime('%H:%M')}"
        text = warning if warning else f"⏱ <b>{task.title}</b>\nНапомню {local_str}"
        await callback.message.edit_text(text, parse_mode="HTML")
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

    # ── List snooze (from /list "Перенести" button) ────────────────────────

    @router.callback_query(F.data.startswith("list_snooze:"))
    async def on_list_snooze(callback: CallbackQuery) -> None:
        task_id = callback.data.split(":", 1)[1]
        task = await task_repo.get(task_id)
        if task is None:
            await callback.answer("Задача не найдена.")
            return
        await callback.message.edit_reply_markup(
            reply_markup=snooze_keyboard(task_id, config)
        )
        await callback.answer()

    # ── Done list callbacks (from /done command and completion detection) ──

    @router.callback_query(F.data.startswith("done_list:"))
    async def on_done_list(callback: CallbackQuery) -> None:
        task_id = callback.data.split(":", 1)[1]
        task = await task_repo.get(task_id)
        if task is None:
            await callback.answer("Задача не найдена.")
            return
        await task_repo.update_status(task_id, TaskStatus.DONE)
        name = callback.from_user.username or callback.from_user.first_name
        text = f"✅ Выполнено: <b>{task.title}</b>"
        if callback.message.chat.type != "private":
            text += f" — @{name}"
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Отмечено как выполненное!")

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

    # ── Doc check / delete (from /sources) ────────────────────────────

    @router.callback_query(F.data.startswith("doccheck:"))
    async def on_doc_check(callback: CallbackQuery) -> None:
        source_id = callback.data.split(":", 1)[1]
        if source_repo is None or llm_client is None:
            await callback.answer("Не настроено.")
            return
        await callback.message.edit_text("🔍 Проверяю документ…")
        await callback.answer()
        try:
            from bot.scheduler.jobs import doc_check_job
            await doc_check_job(
                source_id=source_id,
                bot=bot,
                source_repo=source_repo,
                llm_client=llm_client,
                config=config,
                report_chat_id=callback.message.chat.id,
                settings_repo=settings_repo,
            )
            await callback.message.edit_text("✅ Проверка завершена.")
        except Exception as e:
            await callback.message.edit_text(f"❌ Ошибка: {e}")

    # ── Sheet settings (from /watch google_sheet) ───────────────────────

    @router.callback_query(F.data.startswith("sheetedit:"))
    async def on_sheet_edit(callback: CallbackQuery, state: FSMContext) -> None:
        sheet_id = callback.data.split(":", 1)[1]
        from bot.db.repository import WatchedSheetRepo
        sheet_repo = WatchedSheetRepo(task_repo.conn)
        sheet = await sheet_repo.get(sheet_id)
        if sheet is None:
            await callback.answer("Лист не найден.")
            return
        await state.set_state(WatchStates.editing_sheet_days)
        await state.update_data(sheet_id=sheet_id)
        await callback.message.reply(
            f"Лист <b>{sheet.sheet_name}</b>\n"
            f"Сейчас: за {sheet.reminder_lead_days} дн.\n\n"
            "Введи новое количество дней:",
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("sheetdone:"))
    async def on_sheet_done(callback: CallbackQuery) -> None:
        await callback.message.edit_text("✅ Настройка листов завершена.")
        await callback.answer()

    # ── Source settings (from /sources) ───────────────────────────────

    @router.callback_query(F.data.startswith("sheetsettings:"))
    async def on_sheet_settings(callback: CallbackQuery) -> None:
        source_id = callback.data.split(":", 1)[1]
        from bot.db.repository import WatchedSheetRepo
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        sheet_repo = WatchedSheetRepo(task_repo.conn)
        sheets = await sheet_repo.list_for_source(source_id)
        if not sheets:
            await callback.answer("Нет листов.")
            return
        builder = InlineKeyboardBuilder()
        for s in sheets:
            status = "✅" if s.enabled else "❌"
            builder.row(InlineKeyboardButton(
                text=f"✏️ {s.sheet_name} ({s.reminder_lead_days} дн.) {status}",
                callback_data=f"sheetedit:{s.id}",
            ))
        await callback.message.edit_text(
            "⚙️ <b>Настройки листов:</b>",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("docdel:"))
    async def on_doc_delete(callback: CallbackQuery) -> None:
        source_id = callback.data.split(":", 1)[1]
        if source_repo is None:
            await callback.answer("Не настроено.")
            return
        await source_repo.delete(source_id)
        try:
            scheduler.remove_job(f"doccheck_{source_id}")
        except Exception:
            pass
        await callback.message.edit_text("🗑 Документ удалён из наблюдения.")
        await callback.answer()

    return router
