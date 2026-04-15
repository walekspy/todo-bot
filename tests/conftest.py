import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, MagicMock
from bot.config import Config
from pathlib import Path


@pytest.fixture
def config():
    return Config(
        bot_token="test_token",
        anthropic_api_key="test_key",
        database_path=Path(":memory:"),
        gdrive_service_account_json=Path("credentials/service_account.json"),
        gdrive_backup_folder_id="test_folder",
        snooze_evening_hour=19,
        snooze_morning_hour=9,
        escalation_snooze_count=3,
    )


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite database with schema applied."""
    async with aiosqlite.connect(":memory:") as conn:
        from bot.db.database import create_tables
        await create_tables(conn)
        yield conn


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    return bot


@pytest.fixture
def mock_anthropic():
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client
