import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
from aiogram import Bot
from bot.config import Config
from bot.db.models import TaskStatus
from bot.db.repository import TaskRepo, WatchedSourceRepo, ChatSettingsRepo
from bot.notifications.sender import send_task_reminder, send_event_alert
from bot.llm.doc_analyzer import analyze_doc
from bot.adapters.google_doc import fetch_doc_content
import anthropic

logger = logging.getLogger(__name__)


async def task_reminder_job(
    task_id: str,
    bot: Bot,
    task_repo: TaskRepo,
    config: Config,
    scheduler: "AsyncIOScheduler" = None,
) -> None:
    task = await task_repo.get(task_id)
    if task is None:
        logger.warning("task_reminder_job: task %s not found", task_id)
        return
    # Only stop if the task is terminated (done or cancelled).
    if task.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
        return
    now = datetime.now(timezone.utc)
    if task.snoozed_until and task.snoozed_until > now:
        # Snoozed - reschedule to fire at snooze expiry
        if scheduler:
            scheduler.add_job(
                task_reminder_job,
                trigger="date",
                run_date=task.snoozed_until,
                id=f"reminder_{task_id}",
                replace_existing=True,
                kwargs={
                    "task_id": task_id, "bot": bot,
                    "task_repo": task_repo, "config": config,
                    "scheduler": scheduler,
                },
            )
        return
    # Recurring task whose remind_at is significantly in the past
    # (e.g. after a long restart). Allow ±5 min grace for normal scheduling jitter.
    if task.recurrence and task.remind_at and task.remind_at < now - timedelta(minutes=5):
        from croniter import croniter
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(config.timezone)
        base = task.remind_at.astimezone(tz)
        cron = croniter(task.recurrence, base)
        next_dt = cron.get_next(datetime)
        while next_dt <= datetime.now(tz):
            next_dt = cron.get_next(datetime)
        next_utc = next_dt.astimezone(timezone.utc)
        await task_repo.reschedule(task_id, next_utc)
        if scheduler:
            scheduler.add_job(
                task_reminder_job,
                trigger="date",
                run_date=next_utc,
                id=f"reminder_{task_id}",
                replace_existing=True,
                kwargs={
                    "task_id": task_id, "bot": bot,
                    "task_repo": task_repo, "config": config,
                    "scheduler": scheduler,
                },
            )
        logger.info("task_reminder_job: advanced past-due recurring %s to %s", task_id, next_dt)
        return
    await send_task_reminder(bot, task, config)
    # Auto re-remind in 30 minutes if no action is taken
    if scheduler:
        scheduler.add_job(
            task_reminder_job,
            trigger="date",
            run_date=now + timedelta(minutes=30),
            id=f"reminder_{task_id}",
            replace_existing=True,
            kwargs={
                "task_id": task_id, "bot": bot,
                "task_repo": task_repo, "config": config,
                "scheduler": scheduler,
            },
        )


async def _resolve_alert_chat(settings_repo: Optional[ChatSettingsRepo], source_chat_id: int) -> int:
    """Route Google Doc event alerts to notify_chat_id if set, else back to source chat."""
    if settings_repo is None:
        return source_chat_id
    settings = await settings_repo.get(source_chat_id)
    if settings and settings.notify_chat_id:
        return settings.notify_chat_id
    return source_chat_id


async def doc_check_job(
    source_id: str,
    bot: Bot,
    source_repo: WatchedSourceRepo,
    llm_client: anthropic.AsyncAnthropic,
    config: Config,
    report_chat_id: int = None,
    settings_repo: Optional[ChatSettingsRepo] = None,
) -> None:
    sources = await source_repo.list_all()
    source = next((s for s in sources if s.id == source_id), None)
    if source is None:
        logger.warning("doc_check_job: source %s not found", source_id)
        return

    now = datetime.now(timezone.utc).date()

    if source.source_type == "google_sheet":
        await _check_google_sheet(source, bot, source_repo, llm_client, config, now, report_chat_id, settings_repo)
    else:
        await _check_google_doc(source, bot, source_repo, llm_client, config, now, report_chat_id, settings_repo)

    await source_repo.update_last_checked(source_id, datetime.now(timezone.utc))


async def _check_google_doc(source, bot, source_repo, llm_client, config, now, report_chat_id, settings_repo=None):
    try:
        content = await fetch_doc_content(source.url)
    except ValueError as e:
        logger.error("doc_check_job: failed to fetch %s: %s", source.url, e)
        return

    events = await analyze_doc(llm_client, content, reminder_lead_days_hint=None)

    alert_chat = await _resolve_alert_chat(settings_repo, source.chat_id)
    alerted = 0
    for event in events:
        days_until = (event.date - now).days
        if 0 <= days_until <= event.reminder_lead_days:
            await send_event_alert(bot, alert_chat, event, config)
            alerted += 1

    if report_chat_id is not None:
        await _send_report(bot, report_chat_id, events, now)


async def _check_google_sheet(source, bot, source_repo, llm_client, config, now, report_chat_id, settings_repo=None):
    import asyncio
    from bot.adapters.google_sheet import fetch_sheet_content
    from bot.db.repository import WatchedSheetRepo

    sheet_repo = WatchedSheetRepo(source_repo.conn)
    sheets = await sheet_repo.list_for_source(source.id)

    alert_chat = await _resolve_alert_chat(settings_repo, source.chat_id)
    all_report_lines = []
    for sheet in sheets:
        if not sheet.enabled:
            continue
        try:
            content = await asyncio.to_thread(
                fetch_sheet_content,
                config.gdrive_service_account_json,
                source.url,
                sheet.sheet_name,
            )
        except Exception as e:
            logger.error("Failed to fetch sheet '%s': %s", sheet.sheet_name, e)
            continue

        if not content.strip():
            continue

        events = await analyze_doc(
            llm_client, content,
            reminder_lead_days_hint=sheet.reminder_lead_days,
        )

        for event in events:
            days_until = (event.date - now).days
            if 0 <= days_until <= event.reminder_lead_days:
                await send_event_alert(bot, alert_chat, event, config)

        if report_chat_id is not None and events:
            all_report_lines.append(f"\n📊 <b>{sheet.sheet_name}</b> (за {sheet.reminder_lead_days} дн.):")
            for event in events:
                days_until = (event.date - now).days
                soon = days_until <= event.reminder_lead_days
                marker = " ⚠️" if soon else ""
                date_str = event.date.strftime("%d.%m")
                all_report_lines.append(
                    f"  • <b>{event.title}</b> — {date_str} "
                    f"(через {days_until} дн.){marker}"
                )

    if report_chat_id is not None:
        if not all_report_lines:
            await bot.send_message(report_chat_id, "Событий в таблице не найдено.")
        else:
            text = "📋 <b>Результаты проверки:</b>\n" + "\n".join(all_report_lines)
            await bot.send_message(report_chat_id, text, parse_mode="HTML")


async def _send_report(bot, chat_id, events, now):
    if not events:
        await bot.send_message(chat_id, "Событий в документе не найдено.")
    else:
        lines = []
        for event in events:
            days_until = (event.date - now).days
            soon = days_until <= event.reminder_lead_days
            marker = " ⚠️" if soon else ""
            date_str = event.date.strftime("%d.%m")
            lines.append(
                f"• <b>{event.title}</b> — {date_str} "
                f"(через {days_until} дн., напомню за {event.reminder_lead_days}){marker}"
            )
        text = (
            f"📋 <b>Найдено событий: {len(events)}</b>\n\n"
            + "\n".join(lines)
        )
        await bot.send_message(chat_id, text, parse_mode="HTML")


async def daily_summary_job(
    bot: Bot,
    task_repo: TaskRepo,
    config: Config,
) -> None:
    """Send a daily summary of completed tasks to each chat."""
    tz = ZoneInfo(config.timezone)
    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    start_utc = today_start.astimezone(timezone.utc)
    end_utc = today_end.astimezone(timezone.utc)
    date_str = today_start.strftime("%d.%m.%Y")

    chat_ids = await task_repo.list_chats_with_done(start_utc, end_utc)
    if not chat_ids:
        logger.info("daily_summary: no completed tasks for %s", date_str)
        return

    for chat_id in chat_ids:
        tasks = await task_repo.list_done_between(chat_id, start_utc, end_utc)
        if not tasks:
            continue

        lines = [f"📊 <b>Итоги дня — {date_str}</b>\n"]
        lines.append(f"✅ Выполнено задач: <b>{len(tasks)}</b>\n")
        for t in tasks:
            line = f"• {t.title}"
            if t.assignee_username:
                line += f" — @{t.assignee_username}"
            lines.append(line)

        try:
            await bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
        except Exception as e:
            logger.warning("daily_summary: failed to send to chat %s: %s", chat_id, e)


async def backup_job(db_path: str, backup_chat_id: int, bot: Bot) -> None:
    from bot.backup.telegram_backup import send_backup
    from pathlib import Path
    await send_backup(Path(db_path), backup_chat_id, bot)
