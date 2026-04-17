import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from aiogram import Bot, Dispatcher
from bot.config import load_config
from bot.db.database import get_connection
from bot.db.repository import TaskRepo, WatchedSourceRepo, UserRepo
from bot.scheduler.setup import build_scheduler
from bot.handlers.commands import setup_commands_router
from bot.handlers.messages import setup_messages_router
from bot.handlers.callbacks import setup_callbacks_router
from bot.llm.client import build_llm_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()

    async with get_connection(config.database_path) as conn:
        task_repo = TaskRepo(conn)
        source_repo = WatchedSourceRepo(conn)
        user_repo = UserRepo(conn)

        llm_client = build_llm_client(config.llm_provider, config.llm_api_key, config.llm_model)

        bot = Bot(token=config.bot_token)
        dp = Dispatcher()

        # Scheduler — dedicated DB file to avoid APScheduler schema in app DB
        scheduler_db = config.database_path.parent / "scheduler.db"
        scheduler = build_scheduler(scheduler_db)
        scheduler.start()

        # Build routers (scheduler and bot passed for job registration)
        commands_router = setup_commands_router(
            task_repo, source_repo, user_repo, llm_client, config,
            scheduler=scheduler, bot=bot,
        )
        messages_router, pending_tasks = setup_messages_router(llm_client, config)
        callbacks_router = setup_callbacks_router(
            task_repo, config, pending_tasks, scheduler=scheduler, bot=bot,
        )

        # Order matters: callbacks and commands before catch-all text handler
        dp.include_router(commands_router)
        dp.include_router(callbacks_router)
        dp.include_router(messages_router)

        # Startup reconciliation: reschedule reminders for all existing pending tasks
        from bot.scheduler.jobs import task_reminder_job, doc_check_job
        pending_tasks_list = await task_repo.list_all_pending()
        now = datetime.now(timezone.utc)
        for t in pending_tasks_list:
            fire_at = t.remind_at if t.remind_at > now else now + timedelta(seconds=10)
            scheduler.add_job(
                task_reminder_job,
                trigger="date",
                run_date=fire_at,
                id=f"reminder_{t.id}",
                replace_existing=True,
                kwargs={
                    "task_id": t.id,
                    "bot": bot,
                    "task_repo": task_repo,
                    "config": config,
                },
            )

        # Schedule daily doc checks for all existing watched sources
        all_sources = await source_repo.list_all()
        for source in all_sources:
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
                    "source_repo": source_repo,
                    "llm_client": llm_client,
                    "config": config,
                },
            )

        # Daily backup at 03:00 UTC
        if config.gdrive_backup_folder_id:
            scheduler.add_job(
                "bot.scheduler.jobs:backup_job",
                trigger="cron",
                hour=3,
                minute=0,
                id="daily_backup",
                replace_existing=True,
                kwargs={
                    "db_path": str(config.database_path),
                    "gdrive_folder_id": config.gdrive_backup_folder_id,
                    "service_account_json": str(config.gdrive_service_account_json),
                },
            )

        logger.info("Bot started. %d pending reminders scheduled.", len(pending_tasks_list))

        try:
            await dp.start_polling(bot)
        finally:
            scheduler.shutdown(wait=False)
            logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
