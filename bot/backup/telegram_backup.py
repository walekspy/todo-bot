import logging
from datetime import datetime, timezone
from pathlib import Path
from aiogram import Bot
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)


async def send_backup(db_path: Path, chat_id: int, bot: Bot) -> None:
    if not db_path.exists():
        logger.warning("Backup: database file not found at %s — skipping", db_path)
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"bot_backup_{timestamp}.db"
    document = FSInputFile(db_path, filename=filename)
    await bot.send_document(
        chat_id=chat_id,
        document=document,
        caption=f"🗄 Бэкап БД — {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC",
    )
    logger.info("Backup: sent %s to chat %s", filename, chat_id)
