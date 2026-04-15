import logging
from datetime import datetime, timezone
from aiogram import Bot
from bot.config import Config
from bot.db.models import TaskStatus
from bot.db.repository import TaskRepo, WatchedSourceRepo
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


async def doc_check_job(
    source_id: str,
    bot: Bot,
    source_repo: WatchedSourceRepo,
    llm_client: anthropic.AsyncAnthropic,
    config: Config,
) -> None:
    sources = await source_repo.list_all()
    source = next((s for s in sources if s.id == source_id), None)
    if source is None:
        logger.warning("doc_check_job: source %s not found", source_id)
        return

    try:
        content = await fetch_doc_content(source.url)
    except ValueError as e:
        logger.error("doc_check_job: failed to fetch %s: %s", source.url, e)
        return

    events = await analyze_doc(llm_client, content, reminder_lead_days_hint=None)
    now = datetime.now(timezone.utc).date()

    for event in events:
        days_until = (event.date - now).days
        if 0 <= days_until <= event.reminder_lead_days:
            await send_event_alert(bot, source.chat_id, event, config)

    await source_repo.update_last_checked(source_id, datetime.now(timezone.utc))


async def backup_job(db_path: str, gdrive_folder_id: str, service_account_json: str) -> None:
    from bot.backup.gdrive import upload_backup
    from pathlib import Path
    await upload_backup(Path(db_path), gdrive_folder_id, Path(service_account_json))
