import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.config import Config
from bot.db.models import Task, Priority, WatchedSource, User
from bot.db.repository import TaskRepo, WatchedSourceRepo, UserRepo
from bot.keyboards.confirmation import confirm_keyboard
from bot.keyboards.task_list import done_list_keyboard
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from bot.llm.client import LLMClient


def setup_commands_router(
    task_repo: TaskRepo,
    source_repo: WatchedSourceRepo,
    user_repo: UserRepo,
    llm_client: "LLMClient",
    config: Config,
    scheduler: AsyncIOScheduler = None,
    bot: Bot = None,
) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
        )
        await user_repo.upsert(user)
        await message.answer(
            "👋 Привет! Я бот-планировщик.\n\n"
            "Просто напиши что нужно сделать и когда — я всё запомню.\n\n"
            "Команды: /list /today /watch /sources /family"
        )

    @router.message(Command("add"))
    async def cmd_add(message: Message, state: FSMContext) -> None:
        from bot.handlers.snooze_fsm import AddTaskStates
        await state.set_state(AddTaskStates.waiting_for_task)
        await message.answer(
            "Напиши задачу и время, например:\n"
            "<code>Купить молоко завтра в 10</code>\n"
            "<code>Позвонить врачу в пятницу в 15:00</code>\n"
            "<code>Заплатить за интернет через 3 дня</code>",
            parse_mode="HTML",
        )

    @router.message(Command("list"))
    async def cmd_list(message: Message) -> None:
        tasks = await task_repo.list_active(chat_id=message.chat.id)
        if not tasks:
            await message.answer("Нет активных задач.")
            return
        tz = ZoneInfo(config.timezone)
        for t in tasks:
            due = t.remind_at.astimezone(tz).strftime("%d.%m %H:%M") if t.remind_at else "—"
            emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(t.priority.value, "⚪")
            text = f"{emoji} <b>{t.title}</b>\n📅 {due}"
            if t.notes:
                text += f"\n<i>{t.notes}</i>"
            from bot.keyboards.task_list import done_list_keyboard
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            title_short = t.title if len(t.title) <= 28 else t.title[:25] + "…"
            builder.row(
                InlineKeyboardButton(text="✅ Готово", callback_data=f"done_list:{t.id}"),
                InlineKeyboardButton(text="⏱ Перенести", callback_data=f"list_snooze:{t.id}"),
            )
            await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

    @router.message(Command("today"))
    async def cmd_today(message: Message) -> None:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tasks = await task_repo.list_today(chat_id=message.chat.id, date_str=today_str)
        if not tasks:
            await message.answer("На сегодня задач нет.")
            return
        lines = [f"• {t.title}" for t in tasks]
        await message.answer(
            "📅 <b>Сегодня:</b>\n\n" + "\n".join(lines),
            parse_mode="HTML",
        )

    @router.message(Command("done"))
    async def cmd_done(message: Message) -> None:
        tasks = await task_repo.list_active(chat_id=message.chat.id)
        if not tasks:
            await message.answer("Нет активных задач.")
            return
        await message.answer(
            "Выбери задачу которую выполнил:",
            reply_markup=done_list_keyboard(tasks),
        )

    @router.message(Command("watch"))
    async def cmd_watch(message: Message, state: FSMContext) -> None:
        from bot.handlers.snooze_fsm import WatchStates
        await state.set_state(WatchStates.waiting_for_url)
        await message.answer(
            "Отправь ссылку на Google Doc для отслеживания:"
        )

    @router.message(Command("sources"))
    async def cmd_sources(message: Message) -> None:
        sources = await source_repo.list_for_chat(message.chat.id)
        if not sources:
            await message.answer("Нет наблюдаемых документов. Добавь через /watch")
            return
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        for s in sources:
            url_short = s.url[:60] + "…" if len(s.url) > 60 else s.url
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text="🔍 Проверить", callback_data=f"doccheck:{s.id}"),
            )
            if s.source_type == "google_sheet":
                builder.row(
                    InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"sheetsettings:{s.id}"),
                )
            builder.row(
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"docdel:{s.id}"),
            )
            emoji = "📊" if s.source_type == "google_sheet" else "📄"
            await message.answer(
                f"{emoji} {s.source_type}: {url_short}",
                reply_markup=builder.as_markup(),
            )

    @router.message(Command("sync"))
    async def cmd_sync(message: Message) -> None:
        if config.google_tasks_token_path is None:
            await message.answer("Google Tasks не настроен. Добавь GOOGLE_TASKS_TOKEN_PATH в .env")
            return
        if not config.google_tasks_token_path.exists():
            await message.answer(
                "Токен не найден. Запусти один раз:\n<code>python get_google_token.py</code>",
                parse_mode="HTML",
            )
            return
        msg = await message.answer("🔄 Синхронизирую с Google Tasks…")
        try:
            from bot.sync.google_tasks import sync_google_tasks
            stats = await sync_google_tasks(
                task_repo=task_repo,
                token_path=config.google_tasks_token_path,
                default_owner_id=message.from_user.id,
                default_chat_id=message.chat.id,
                tz_name=config.timezone,
            )
            await msg.edit_text(f"✅ Синхронизация завершена\n\n{stats}")
            # For tasks pulled from Google without time — ask user to set time
            if stats.no_time_tasks:
                from bot.keyboards.snooze import snooze_keyboard
                await message.answer(
                    "⏰ <b>Задачи без времени</b> — укажи когда напомнить:",
                    parse_mode="HTML",
                )
                for task_id, title in stats.no_time_tasks:
                    await message.answer(
                        f"📌 {title}",
                        reply_markup=snooze_keyboard(task_id),
                    )
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка синхронизации: {e}")

    @router.message(Command("family"))
    async def cmd_family(message: Message) -> None:
        tasks = await task_repo.list_active(chat_id=message.chat.id)
        family_tasks = [t for t in tasks if t.is_family]
        if not family_tasks:
            await message.answer("Нет семейных задач.")
            return
        lines = []
        for t in family_tasks:
            if t.assignee_id:
                user = await user_repo.get(t.assignee_id)
                assignee = f"@{user.username}" if (user and user.username) else f"user#{t.assignee_id}"
            else:
                assignee = "не назначено"
            lines.append(f"• {t.title} → {assignee} [{t.status.value}]")
        await message.answer(
            "👨‍👩‍👧 <b>Семейные задачи:</b>\n\n" + "\n".join(lines),
            parse_mode="HTML",
        )

    return router
