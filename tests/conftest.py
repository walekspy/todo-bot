import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock
from bot.config import Config
from pathlib import Path


@pytest.fixture
def config():
    return Config(
        bot_token="test_token",
        llm_provider="groq",
        llm_api_key="test_key",
        llm_model="llama-3.3-70b-versatile",
        database_path=Path(":memory:"),
        gdrive_service_account_json=Path("credentials/service_account.json"),
        gdrive_backup_folder_id="test_folder",
        backup_chat_id=None,
        snooze_morning_hour=9,
        night_start_hour=23,
        night_end_hour=7,
        escalation_snooze_count=3,
        timezone="UTC",
        google_tasks_token_path=None,
    )


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite database with schema applied."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
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
def mock_llm_client():
    from bot.llm.client import LLMClient
    client = AsyncMock(spec=LLMClient)
    return client
