"""FSM handler for custom snooze time input."""
from datetime import datetime
from zoneinfo import ZoneInfo
import dateparser
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from bot.config import Config
from bot.db.repository import TaskRepo


class CustomSnoozeStates(StatesGroup):
    waiting_for_time = State()


class AddTaskStates(StatesGroup):
    waiting_for_task = State()


class WatchStates(StatesGroup):
    waiting_for_url = State()
    editing_sheet_days = State()


def setup_snooze_fsm_router(
    task_repo: TaskRepo,
    config: Config,
    llm_client,
    scheduler: AsyncIOScheduler,
    bot: Bot,
    source_repo=None,
) -> Router:
    router = Router()
    _source_repo = source_repo

    @router.message(CustomSnoozeStates.waiting_for_time)
    async def on_custom_time_input(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        task_id = data.get("task_id")
        await state.clear()

        tz = ZoneInfo(config.timezone)
        now = datetime.now(tz)

        until = dateparser.parse(
            message.text or "",
            languages=["ru", "en"],
            settings={
                "TIMEZONE": config.timezone,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now,
            },
        )

        if until is None:
            await message.answer(
                "Не понял время. Попробуй написать например:\n"
                "<code>завтра в 10:00</code> или <code>через 2 часа</code>",
                parse_mode="HTML",
            )
            return

        if until <= now.astimezone(until.tzinfo):
            await message.answer("Это время уже прошло. Укажи время в будущем.")
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
            },
        )

        task = await task_repo.get(task_id)
        title = task.title if task else "задача"
        local_dt = until.astimezone(tz)
        local_str = f"{local_dt.strftime('%d.%m')} в {local_dt.strftime('%H:%M')}"
        await message.answer(
            f"⏱ <b>{title}</b>\nНапомню {local_str}",
            parse_mode="HTML",
        )

    @router.message(AddTaskStates.waiting_for_task)
    async def on_add_task_input(message: Message, state: FSMContext) -> None:
        await state.clear()
        if not message.text or not message.text.strip():
            await message.answer("Пустое сообщение, попробуй ещё раз через /add.")
            return

        from bot.llm.extractor import extract_tasks
        from bot.db.models import Task
        from bot.keyboards.confirmation import confirm_keyboard
        import uuid

        try:
            raw_tasks = await extract_tasks(
                llm_client, message.text, tz_name=config.timezone
            )
        except Exception as e:
            await message.answer(f"Ошибка обработки: {e}")
            return

        if not raw_tasks:
            await message.answer("Не удалось распознать задачу. Попробуй написать иначе.")
            return

        tz = ZoneInfo(config.timezone)
        for raw in raw_tasks:
            tmp_id = str(uuid.uuid4())
            from bot.handlers.messages import _pending
            _pending[tmp_id] = raw
            local_dt = raw.remind_at.astimezone(tz)
            time_str = f"{local_dt.strftime('%d.%m')} в {local_dt.strftime('%H:%M')}"
            priority_label = {"low": "🔵 низкий", "medium": "🟡 средний", "high": "🔴 высокий"}.get(
                raw.priority.value, raw.priority.value
            )
            text = (
                f"📝 <b>{raw.title}</b>\n"
                f"📅 {time_str}\n"
                f"Приоритет: {priority_label}"
            )
            if raw.notes:
                text += f"\n<i>{raw.notes}</i>"
            await message.answer(
                text,
                parse_mode="HTML",
                reply_markup=confirm_keyboard(tmp_id),
            )

    @router.message(WatchStates.waiting_for_url)
    async def on_watch_url_input(message: Message, state: FSMContext) -> None:
        url = (message.text or "").strip()
        if not url.startswith("http"):
            await state.clear()
            await message.answer(
                "Это не похоже на ссылку. Попробуй ещё раз через /watch"
            )
            return

        from bot.adapters.google_sheet import is_sheets_url

        if is_sheets_url(url):
            await _handle_sheets_url(message, state, url)
        else:
            await _handle_doc_url(message, state, url)

    async def _handle_doc_url(message: Message, state: FSMContext, url: str) -> None:
        await state.clear()
        from bot.db.models import WatchedSource
        source = WatchedSource(
            owner_id=message.from_user.id,
            chat_id=message.chat.id,
            url=url,
            source_type="google_doc",
        )
        await _source_repo.save(source)

        if scheduler is not None and bot is not None:
            from bot.scheduler.jobs import doc_check_job
            scheduler.add_job(
                doc_check_job,
                trigger="cron",
                hour=6,
                minute=0,
                id=f"doccheck_{source.id}",
                replace_existing=True,
                kwargs={
                    "source_id": source.id,
                    "bot": bot,
                    "source_repo": _source_repo,
                    "llm_client": llm_client,
                    "config": config,
                },
            )
        await message.answer(
            "✅ Документ добавлен для слежения.\n"
            "Буду проверять раз в сутки и напоминать о приближающихся датах."
        )

    async def _handle_sheets_url(message: Message, state: FSMContext, url: str) -> None:
        import asyncio
        from bot.adapters.google_sheet import fetch_sheet_names
        from bot.db.models import WatchedSource, WatchedSheet
        from bot.db.repository import WatchedSheetRepo
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton

        await message.answer("📊 Читаю список листов…")

        try:
            sheet_names = await asyncio.to_thread(
                fetch_sheet_names, config.gdrive_service_account_json, url
            )
        except Exception as e:
            await state.clear()
            await message.answer(f"❌ Ошибка чтения таблицы: {e}")
            return

        if not sheet_names:
            await state.clear()
            await message.answer("В таблице нет листов.")
            return

        # Ask LLM for suggested reminder_lead_days per sheet name
        prompt = (
            "Given these spreadsheet sheet names, suggest reminder_lead_days (integer) "
            "for each based on the likely content type. Return JSON object: "
            '{sheet_name: days, ...}. Sheet names: ' + str(sheet_names)
        )
        defaults = {}
        try:
            import json
            raw = await llm_client.complete(
                "Return only JSON, no markdown.", prompt
            )
            defaults = json.loads(raw.strip())
        except Exception:
            pass

        # Save source
        source = WatchedSource(
            owner_id=message.from_user.id,
            chat_id=message.chat.id,
            url=url,
            source_type="google_sheet",
        )
        await _source_repo.save(source)

        # Save sheets with defaults
        sheet_repo = WatchedSheetRepo(_source_repo.conn)
        sheets = []
        for name in sheet_names:
            days = defaults.get(name, 3)
            if not isinstance(days, int) or days < 0:
                days = 3
            sheets.append(WatchedSheet(
                source_id=source.id,
                sheet_name=name,
                reminder_lead_days=days,
            ))
        await sheet_repo.save_many(sheets)

        # Schedule daily check
        if scheduler is not None and bot is not None:
            from bot.scheduler.jobs import doc_check_job
            scheduler.add_job(
                doc_check_job,
                trigger="cron",
                hour=6,
                minute=0,
                id=f"doccheck_{source.id}",
                replace_existing=True,
                kwargs={
                    "source_id": source.id,
                    "bot": bot,
                    "source_repo": _source_repo,
                    "llm_client": llm_client,
                    "config": config,
                },
            )

        # Show sheets with edit buttons
        lines = []
        for s in sheets:
            lines.append(f"• {s.sheet_name} — за {s.reminder_lead_days} дн.")

        builder = InlineKeyboardBuilder()
        for s in sheets:
            builder.row(InlineKeyboardButton(
                text=f"✏️ {s.sheet_name} ({s.reminder_lead_days} дн.)",
                callback_data=f"sheetedit:{s.id}",
            ))
        builder.row(InlineKeyboardButton(
            text="✅ Готово",
            callback_data=f"sheetdone:{source.id}",
        ))

        await state.clear()
        await message.answer(
            "📊 <b>Таблица добавлена!</b>\n\n"
            + "\n".join(lines)
            + "\n\nНажми ✏️ чтобы изменить дни напоминания:",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )

    @router.message(WatchStates.editing_sheet_days)
    async def on_sheet_days_input(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        sheet_id = data.get("sheet_id")
        await state.clear()

        text = (message.text or "").strip()
        try:
            days = int(text)
            if days < 0:
                raise ValueError
        except ValueError:
            await message.answer("Введи положительное число (количество дней).")
            return

        from bot.db.repository import WatchedSheetRepo
        sheet_repo = WatchedSheetRepo(_source_repo.conn)
        await sheet_repo.update_lead_days(sheet_id, days)
        sheet = await sheet_repo.get(sheet_id)
        name = sheet.sheet_name if sheet else "лист"
        await message.answer(f"✅ <b>{name}</b> — напоминание за {days} дн.", parse_mode="HTML")

    return router
