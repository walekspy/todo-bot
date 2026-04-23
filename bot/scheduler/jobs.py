import logging
from datetime import datetime, timezone
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
) -> None:
    task = await task_repo.get(task_id)
    if task is None:
        logger.warning("task_reminder_job: task %s not found", task_id)
        return
    if task.status in (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.ACTIVE):
        return
    now = datetime.now(timezone.utc)
    if task.snoozed_until and task.snoozed_until > now:
        return
    await send_task_reminder(bot, task, config)


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


async def checkin_job(
    task_id: str,
    bot: Bot,
    task_repo: TaskRepo,
    config: Config,
) -> None:
    """30-minute follow-up after 'take in work': reset to PENDING and remind again."""
    task = await task_repo.get(task_id)
    if task is None:
        return
    if task.status == TaskStatus.DONE:
        return  # user already marked done, skip
    # Reset to pending so the reminder fires normally
    await task_repo.update_status(task_id, TaskStatus.PENDING)
    await send_task_reminder(bot, task, config)


async def backup_job(db_path: str, backup_chat_id: int, bot: Bot) -> None:
    from bot.backup.telegram_backup import send_backup
    from pathlib import Path
    await send_backup(Path(db_path), backup_chat_id, bot)
