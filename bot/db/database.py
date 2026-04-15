import aiosqlite
from pathlib import Path


CREATE_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
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

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    family_chat_id INTEGER,
    created_at TEXT NOT NULL
)
"""


async def create_tables(conn: aiosqlite.Connection) -> None:
    await conn.execute(CREATE_TASKS_TABLE)
    await conn.execute(CREATE_WATCHED_SOURCES_TABLE)
    await conn.execute(CREATE_USERS_TABLE)
    await conn.commit()


async def get_connection(db_path: Path) -> aiosqlite.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await create_tables(conn)
    return conn
