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
from bot.db.repository import TaskRepo, WatchedSourceRepo, UserRepo, ChatSettingsRepo
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
    settings_repo: ChatSettingsRepo = None,
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
            if t.assignee_username:
                text += f"\n👤 @{t.assignee_username}"
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
        from datetime import timedelta
        tz = ZoneInfo(config.timezone)
        now_local = datetime.now(tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        tasks = await task_repo.list_today(chat_id=message.chat.id, start=start_utc, end=end_utc)
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

    @router.message(Command("backup"))
    async def cmd_backup(message: Message) -> None:
        chat_id = config.backup_chat_id or message.chat.id
        msg = await message.answer("⏳ Делаю бэкап...")
        try:
            from bot.backup.telegram_backup import send_backup
            await send_backup(config.database_path, chat_id, message.bot)
            target = "сюда" if chat_id == message.chat.id else f"в чат {chat_id}"
            await msg.edit_text(f"✅ Бэкап отправлен {target}.")
        except Exception as e:
            import html
            try:
                await msg.edit_text(f"❌ Ошибка бэкапа:\n<code>{html.escape(str(e))}</code>", parse_mode="HTML")
            except Exception:
                await message.answer(f"❌ Ошибка бэкапа:\n{str(e)[:500]}")

    @router.message(Command("chatid"))
    async def cmd_chatid(message: Message) -> None:
        await message.answer(
            f"ID этого чата: <code>{message.chat.id}</code>\n\n"
            f"Чтобы напоминания из другого чата приходили сюда, скопируй этот ID "
            f"и выполни в чате задач: <code>/set_notify {message.chat.id}</code>",
            parse_mode="HTML",
        )

    @router.message(Command("set_notify"))
    async def cmd_set_notify(message: Message) -> None:
        if not settings_repo:
            await message.answer("Настройки недоступны.")
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "Укажи ID группы уведомлений:\n"
                "<code>/set_notify -1001234567890</code>\n\n"
                "Узнать ID группы: напиши /chatid в той группе.",
                parse_mode="HTML",
            )
            return
        try:
            notify_id = int(args[1].strip())
        except ValueError:
            await message.answer("Неверный формат. ID должен быть числом, например: -1001234567890")
            return
        if notify_id == message.chat.id:
            await message.answer(
                "⚠️ Это ID текущего чата — напоминания и так приходят сюда. "
                "Укажи ID другого чата, куда хочешь перенаправлять уведомления."
            )
            return
        # Validate bot is a member of target chat
        if bot is not None:
            try:
                target_chat = await bot.get_chat(notify_id)
            except Exception as e:
                await message.answer(
                    f"❌ Не могу достучаться до чата <code>{notify_id}</code>.\n"
                    f"Убедись что:\n"
                    f"• ID указан верно (включая знак минус для групп)\n"
                    f"• Бот добавлен в тот чат\n\n"
                    f"<i>Ошибка: {str(e)[:200]}</i>",
                    parse_mode="HTML",
                )
                return
            target_title = getattr(target_chat, "title", None) or getattr(target_chat, "full_name", None) or str(notify_id)
        else:
            target_title = str(notify_id)
        await settings_repo.set_notify_chat(message.chat.id, notify_id)
        await message.answer(
            f"✅ Напоминания для этого чата будут отправляться в «{target_title}» "
            f"(<code>{notify_id}</code>).\n\n"
            f"Проверить: /notify_status\n"
            f"Отменить: /unset_notify",
            parse_mode="HTML",
        )

    @router.message(Command("unset_notify"))
    async def cmd_unset_notify(message: Message) -> None:
        if not settings_repo:
            await message.answer("Настройки недоступны.")
            return
        existing = await settings_repo.get(message.chat.id)
        if existing is None or existing.notify_chat_id is None:
            await message.answer("ℹ️ Маршрутизация напоминаний не настроена. Нечего отключать.")
            return
        await settings_repo.clear_notify_chat(message.chat.id)
        await message.answer(
            "✅ Маршрутизация отключена. Напоминания снова будут приходить сюда."
        )

    @router.message(Command("notify_status"))
    async def cmd_notify_status(message: Message) -> None:
        if not settings_repo:
            await message.answer("Настройки недоступны.")
            return
        settings = await settings_repo.get(message.chat.id)
        if settings is None or settings.notify_chat_id is None:
            await message.answer(
                "📍 Напоминания приходят в этот же чат.\n\n"
                "Чтобы направить их в отдельный чат, используй /set_notify."
            )
            return
        target_title = str(settings.notify_chat_id)
        if bot is not None:
            try:
                target_chat = await bot.get_chat(settings.notify_chat_id)
                target_title = (
                    getattr(target_chat, "title", None)
                    or getattr(target_chat, "full_name", None)
                    or str(settings.notify_chat_id)
                )
            except Exception:
                target_title = f"{settings.notify_chat_id} (не удалось получить название)"
        await message.answer(
            f"📍 Напоминания из этого чата идут в «{target_title}» "
            f"(<code>{settings.notify_chat_id}</code>).\n\n"
            f"Отменить маршрутизацию: /unset_notify",
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
