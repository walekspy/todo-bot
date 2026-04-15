import uuid
from datetime import datetime, timezone
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from bot.config import Config
from bot.db.models import Task, Priority, WatchedSource, User
from bot.db.repository import TaskRepo, WatchedSourceRepo, UserRepo
from bot.keyboards.confirmation import confirm_keyboard
import anthropic


def setup_commands_router(
    task_repo: TaskRepo,
    source_repo: WatchedSourceRepo,
    user_repo: UserRepo,
    llm_client: anthropic.AsyncAnthropic,
    config: Config,
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
            "Просто напиши что нужно сделать и когда — я всё запомню.\n"
            "Или используй /add для добавления задачи.\n\n"
            "Команды: /list /today /done /watch /sources /family"
        )

    @router.message(Command("list"))
    async def cmd_list(message: Message) -> None:
        tasks = await task_repo.list_active(chat_id=message.chat.id)
        if not tasks:
            await message.answer("Нет активных задач.")
            return
        lines = []
        for t in tasks:
            due = t.remind_at.strftime("%d.%m %H:%M") if t.remind_at else "—"
            emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(t.priority.value, "⚪")
            lines.append(f"{emoji} {t.title} — {due}")
        await message.answer(
            "📋 <b>Активные задачи:</b>\n\n" + "\n".join(lines),
            parse_mode="HTML",
        )

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

    @router.message(Command("watch"))
    async def cmd_watch(message: Message) -> None:
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip().startswith("http"):
            await message.answer("Использование: /watch <ссылка на Google Doc>")
            return
        url = args[1].strip()
        source = WatchedSource(
            owner_id=message.from_user.id,
            chat_id=message.chat.id,
            url=url,
            source_type="google_doc",
        )
        await source_repo.save(source)
        await message.answer(
            "✅ Документ добавлен для слежения.\n"
            "Буду проверять раз в сутки и напоминать о приближающихся датах."
        )

    @router.message(Command("sources"))
    async def cmd_sources(message: Message) -> None:
        sources = await source_repo.list_for_chat(message.chat.id)
        if not sources:
            await message.answer("Нет наблюдаемых документов. Добавь через /watch <url>")
            return
        lines = [f"• {s.source_type}: {s.url[:60]}…" for s in sources]
        await message.answer(
            "🔍 <b>Наблюдаемые документы:</b>\n\n" + "\n".join(lines),
            parse_mode="HTML",
        )

    @router.message(Command("family"))
    async def cmd_family(message: Message) -> None:
        tasks = await task_repo.list_active(chat_id=message.chat.id)
        family_tasks = [t for t in tasks if t.is_family]
        if not family_tasks:
            await message.answer("Нет семейных задач.")
            return
        lines = []
        for t in family_tasks:
            assignee = f"@{t.assignee_id}" if t.assignee_id else "не назначено"
            lines.append(f"• {t.title} → {assignee} [{t.status.value}]")
        await message.answer(
            "👨‍👩‍👧 <b>Семейные задачи:</b>\n\n" + "\n".join(lines),
            parse_mode="HTML",
        )

    return router
