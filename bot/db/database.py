import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator


CREATE_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','done','cancelled')),
    priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low','medium','high')),
    source TEXT NOT NULL DEFAULT 'manual',
    source_ref TEXT,
    due_at TEXT,
    remind_at TEXT NOT NULL,
    recurrence TEXT,
    snoozed_until TEXT,
    snooze_count INTEGER NOT NULL DEFAULT 0,
    owner_id INTEGER NOT NULL,
    assignee_id INTEGER,
    chat_id INTEGER NOT NULL,
    is_family INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""

CREATE_WATCHED_SOURCES_TABLE = """
CREATE TABLE IF NOT EXISTS watched_sources (
    id TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    last_checked TEXT,
    reminder_lead_days INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL
)
"""

CREATE_WATCHED_SHEETS_TABLE = """
CREATE TABLE IF NOT EXISTS watched_sheets (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    reminder_lead_days INTEGER NOT NULL DEFAULT 3,
    enabled INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (source_id) REFERENCES watched_sources(id) ON DELETE CASCADE
)
"""

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    family_chat_id INTEGER,
    created_at TEXT NOT NULL
)
"""

CREATE_CHAT_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id INTEGER PRIMARY KEY,
    notify_chat_id INTEGER
)
"""

CREATE_CHAT_MEMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS chat_members (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (chat_id, user_id)
)
"""


async def create_tables(conn: aiosqlite.Connection) -> None:
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute(CREATE_TASKS_TABLE)
    await conn.execute(CREATE_WATCHED_SOURCES_TABLE)
    await conn.execute(CREATE_WATCHED_SHEETS_TABLE)
    await conn.execute(CREATE_USERS_TABLE)
    await conn.execute(CREATE_CHAT_SETTINGS_TABLE)
    await conn.execute(CREATE_CHAT_MEMBERS_TABLE)
    # Migrations: add new columns if they don't exist yet
    for col, definition in [
        ("updated_at", "TEXT"),
        ("google_task_id", "TEXT"),
        ("google_tasklist_id", "TEXT"),
        ("google_updated_at", "TEXT"),
        ("assignee_username", "TEXT"),
        ("notify_chat_id", "INTEGER"),
    ]:
        try:
            await conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {definition}")
        except Exception:
            pass  # Column already exists
    await conn.commit()


@asynccontextmanager
async def get_connection(db_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        await create_tables(conn)
        yield conn
