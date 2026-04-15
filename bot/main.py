import asyncio
import logging
from pathlib import Path
from aiogram import Bot, Dispatcher
from bot.config import load_config
from bot.db.database import get_connection
from bot.db.repository import TaskRepo, WatchedSourceRepo, UserRepo
from bot.scheduler.setup import build_scheduler
from bot.handlers.commands import setup_commands_router
from bot.handlers.messages import setup_messages_router
from bot.handlers.callbacks import setup_callbacks_router
import anthropic

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

        llm_client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

        bot = Bot(token=config.bot_token)
        dp = Dispatcher()

        # Build routers
        commands_router = setup_commands_router(
            task_repo, source_repo, user_repo, llm_client, config
        )
        messages_router, pending_tasks = setup_messages_router(llm_client, config)
        callbacks_router = setup_callbacks_router(task_repo, config, pending_tasks)

        # Order matters: callbacks and commands before catch-all text handler
        dp.include_router(commands_router)
        dp.include_router(callbacks_router)
        dp.include_router(messages_router)

        # Scheduler — use a dedicated DB file to avoid schema conflicts with app DB
        scheduler_db = config.database_path.parent / "scheduler.db"
        scheduler = build_scheduler(scheduler_db)

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

        scheduler.start()
        logger.info("Bot started. Scheduler running.")

        try:
            await dp.start_polling(bot)
        finally:
            scheduler.shutdown(wait=False)
            logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
