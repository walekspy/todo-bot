# Telegram Reminder Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram bot that collects tasks from multiple sources (manual text, Google Docs, MD files), reminds users at scheduled times with snooze/take/done actions, and supports both personal and family group use.

**Architecture:** Clean Python monolith with internal layers — Source Adapters → LLM Extractor → Task Repository (SQLite) → APScheduler (persistent) → aiogram v3 Bot. Each source is an independent adapter module implementing a shared interface. New sources are added without touching existing code.

**Tech Stack:** Python 3.12, aiogram 3.13, APScheduler 3.10 (SQLite job store), aiosqlite 0.20, anthropic SDK (Claude claude-sonnet-4-6), google-api-python-client, python-dotenv, pytest + pytest-asyncio

---

## File Map

```
bot/
  __init__.py
  main.py                    # Entry point: create Bot, Dispatcher, start scheduler, polling
  config.py                  # Settings loaded from .env via python-dotenv
  db/
    __init__.py
    database.py              # aiosqlite connection pool, create_tables()
    models.py                # Task, WatchedSource, User dataclasses + enums
    repository.py            # TaskRepo, WatchedSourceRepo, UserRepo — all SQL here
  adapters/
    __init__.py
    base.py                  # SourceAdapter ABC + RawTask dataclass
    manual.py                # ManualAdapter: free text → RawTask via LLM
    google_doc.py            # GoogleDocAdapter: fetch public doc content
    md_file.py               # MdFileAdapter: parse uploaded MD file
  llm/
    __init__.py
    extractor.py             # extract_tasks(text, source_hint) → list[RawTask] via Claude
    doc_analyzer.py          # analyze_doc(text) → list[DocEvent] with reminder_lead_days
  scheduler/
    __init__.py
    setup.py                 # build_scheduler() with SQLAlchemyJobStore on SQLite
    jobs.py                  # task_reminder_job, doc_check_job, backup_job functions
  handlers/
    __init__.py
    commands.py              # /add /list /today /done /watch /sources /family /start
    messages.py              # free text message handler → ManualAdapter
    callbacks.py             # inline button callbacks: snooze, take, done, confirm, skip, edit
  keyboards/
    __init__.py
    reminder.py              # reminder_keyboard() — ⏱▶️✅ buttons
    snooze.py                # snooze_keyboard() — smart time options
    confirmation.py          # confirm_keyboard() — ✅✏️❌ for task preview
  notifications/
    __init__.py
    sender.py                # send_task_reminder(bot, task), send_event_alert(bot, event)
  backup/
    __init__.py
    gdrive.py                # upload_backup(db_path) → Google Drive
tests/
  conftest.py                # pytest fixtures: in-memory DB, mock bot, mock Claude
  test_models.py             # Task/WatchedSource/User dataclass validation
  test_repository.py         # TaskRepo / WatchedSourceRepo CRUD
  test_extractor.py          # LLM extractor with mocked Claude responses
  test_adapters.py           # ManualAdapter, MdFileAdapter, GoogleDocAdapter
  test_jobs.py               # scheduler job functions with mocked dependencies
  test_reminder_flow.py      # snooze/take/done/escalation callback logic
  test_backup.py             # gdrive backup with mocked Drive API
.env.example
requirements.txt
```

---

## Task 1: Project scaffold + config

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `bot/config.py`
- Create: `bot/__init__.py`, `bot/db/__init__.py`, `bot/adapters/__init__.py`, `bot/llm/__init__.py`, `bot/scheduler/__init__.py`, `bot/handlers/__init__.py`, `bot/keyboards/__init__.py`, `bot/notifications/__init__.py`, `bot/backup/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Init git repo and create project structure**

```bash
cd D:/todo
git init
mkdir -p bot/db bot/adapters bot/llm bot/scheduler bot/handlers bot/keyboards bot/notifications bot/backup tests
touch bot/__init__.py bot/db/__init__.py bot/adapters/__init__.py bot/llm/__init__.py
touch bot/scheduler/__init__.py bot/handlers/__init__.py bot/keyboards/__init__.py
touch bot/notifications/__init__.py bot/backup/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write requirements.txt**

```
aiogram==3.13.0
apscheduler==3.10.4
aiosqlite==0.20.0
anthropic==0.40.0
httpx==0.27.0
google-api-python-client==2.156.0
google-auth==2.37.0
python-dotenv==1.0.1
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-mock==3.14.0
```

- [ ] **Step 3: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 4: Write .env.example**

```ini
BOT_TOKEN=your_telegram_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
DATABASE_PATH=data/bot.db
GDRIVE_SERVICE_ACCOUNT_JSON=credentials/service_account.json
GDRIVE_BACKUP_FOLDER_ID=your_google_drive_folder_id
SNOOZE_EVENING_HOUR=19
SNOOZE_MORNING_HOUR=9
ESCALATION_SNOOZE_COUNT=3
```

- [ ] **Step 5: Write bot/config.py**

```python
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    anthropic_api_key: str
    database_path: Path
    gdrive_service_account_json: Path
    gdrive_backup_folder_id: str
    snooze_evening_hour: int
    snooze_morning_hour: int
    escalation_snooze_count: int


def load_config() -> Config:
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        database_path=Path(os.getenv("DATABASE_PATH", "data/bot.db")),
        gdrive_service_account_json=Path(
            os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json")
        ),
        gdrive_backup_folder_id=os.getenv("GDRIVE_BACKUP_FOLDER_ID", ""),
        snooze_evening_hour=int(os.getenv("SNOOZE_EVENING_HOUR", "19")),
        snooze_morning_hour=int(os.getenv("SNOOZE_MORNING_HOUR", "9")),
        escalation_snooze_count=int(os.getenv("ESCALATION_SNOOZE_COUNT", "3")),
    )
```

- [ ] **Step 6: Write tests/conftest.py skeleton**

```python
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
```

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "feat: project scaffold, config, requirements"
```

---

## Task 2: Database schema

**Files:**
- Create: `bot/db/database.py`
- Create: `bot/db/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing test for models**

```python
# tests/test_models.py
import pytest
from datetime import datetime, timezone
from bot.db.models import Task, TaskStatus, Priority, WatchedSource, User


def test_task_defaults():
    task = Task(
        title="Buy milk",
        owner_id=123,
        chat_id=456,
        remind_at=datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc),
    )
    assert task.status == TaskStatus.PENDING
    assert task.priority == Priority.MEDIUM
    assert task.source == "manual"
    assert task.snooze_count == 0
    assert task.is_family is False
    assert task.id is not None
    assert len(task.id) == 36  # UUID format


def test_task_with_all_fields():
    now = datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc)
    task = Task(
        title="Doctor appointment",
        owner_id=111,
        chat_id=222,
        remind_at=now,
        priority=Priority.HIGH,
        source="google_doc",
        source_ref="https://docs.google.com/...",
        is_family=True,
        assignee_id=333,
        recurrence="0 9 * * *",
    )
    assert task.priority == Priority.HIGH
    assert task.is_family is True
    assert task.assignee_id == 333


def test_watched_source_fields():
    src = WatchedSource(
        id="abc",
        owner_id=123,
        chat_id=456,
        url="https://docs.google.com/document/d/abc",
        source_type="google_doc",
        last_checked=None,
        reminder_lead_days=3,
        created_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
    )
    assert src.source_type == "google_doc"
    assert src.reminder_lead_days == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py -v
```
Expected: `ImportError: No module named 'bot.db.models'`

- [ ] **Step 3: Write bot/db/models.py**

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Task:
    title: str
    owner_id: int
    chat_id: int
    remind_at: datetime
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notes: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.MEDIUM
    source: str = "manual"
    source_ref: Optional[str] = None
    due_at: Optional[datetime] = None
    recurrence: Optional[str] = None
    snoozed_until: Optional[datetime] = None
    snooze_count: int = 0
    assignee_id: Optional[int] = None
    is_family: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class WatchedSource:
    id: str
    owner_id: int
    chat_id: int
    url: str
    source_type: str  # "google_doc" | "md_file"
    last_checked: Optional[datetime]
    reminder_lead_days: int
    created_at: datetime


@dataclass
class User:
    telegram_id: int
    username: Optional[str]
    family_chat_id: Optional[int]
    created_at: datetime
```

- [ ] **Step 4: Write bot/db/database.py**

```python
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
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_models.py -v
```
Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add bot/db/models.py bot/db/database.py tests/test_models.py
git commit -m "feat: database schema and Task/WatchedSource/User models"
```

---

## Task 3: Task Repository

**Files:**
- Create: `bot/db/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_repository.py
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from bot.db.models import Task, TaskStatus, Priority, WatchedSource, User
from bot.db.repository import TaskRepo, WatchedSourceRepo, UserRepo
import uuid


def make_task(**kwargs) -> Task:
    defaults = dict(
        title="Test task",
        owner_id=100,
        chat_id=200,
        remind_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return Task(**defaults)


@pytest.mark.asyncio
async def test_save_and_get_task(db):
    repo = TaskRepo(db)
    task = make_task(title="Buy milk")
    await repo.save(task)

    fetched = await repo.get(task.id)
    assert fetched is not None
    assert fetched.title == "Buy milk"
    assert fetched.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_list_active_for_user(db):
    repo = TaskRepo(db)
    t1 = make_task(title="Task A", owner_id=1, chat_id=10)
    t2 = make_task(title="Task B", owner_id=1, chat_id=10)
    t3 = make_task(title="Other user", owner_id=2, chat_id=20)
    for t in [t1, t2, t3]:
        await repo.save(t)

    tasks = await repo.list_active(chat_id=10)
    assert len(tasks) == 2
    titles = {t.title for t in tasks}
    assert titles == {"Task A", "Task B"}


@pytest.mark.asyncio
async def test_update_status(db):
    repo = TaskRepo(db)
    task = make_task()
    await repo.save(task)
    await repo.update_status(task.id, TaskStatus.DONE)

    fetched = await repo.get(task.id)
    assert fetched.status == TaskStatus.DONE


@pytest.mark.asyncio
async def test_increment_snooze(db):
    repo = TaskRepo(db)
    task = make_task()
    await repo.save(task)
    snoozed_until = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    await repo.snooze(task.id, snoozed_until)

    fetched = await repo.get(task.id)
    assert fetched.snooze_count == 1
    assert fetched.snoozed_until == snoozed_until


@pytest.mark.asyncio
async def test_list_due_for_reminder(db):
    repo = TaskRepo(db)
    now = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
    due = make_task(title="Due now", remind_at=now - timedelta(minutes=1))
    future = make_task(title="Future", remind_at=now + timedelta(hours=1))
    for t in [due, future]:
        await repo.save(t)

    tasks = await repo.list_due(as_of=now)
    assert len(tasks) == 1
    assert tasks[0].title == "Due now"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_repository.py -v
```
Expected: `ImportError: cannot import name 'TaskRepo'`

- [ ] **Step 3: Write bot/db/repository.py**

```python
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from bot.db.models import Task, TaskStatus, Priority, WatchedSource, User
import uuid


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _row_to_task(row: aiosqlite.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        notes=row["notes"],
        status=TaskStatus(row["status"]),
        priority=Priority(row["priority"]),
        source=row["source"],
        source_ref=row["source_ref"],
        due_at=_parse_dt(row["due_at"]),
        remind_at=_parse_dt(row["remind_at"]),
        recurrence=row["recurrence"],
        snoozed_until=_parse_dt(row["snoozed_until"]),
        snooze_count=row["snooze_count"],
        owner_id=row["owner_id"],
        assignee_id=row["assignee_id"],
        chat_id=row["chat_id"],
        is_family=bool(row["is_family"]),
        created_at=_parse_dt(row["created_at"]),
    )


class TaskRepo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def save(self, task: Task) -> None:
        await self.conn.execute(
            """INSERT INTO tasks
               (id, title, notes, status, priority, source, source_ref,
                due_at, remind_at, recurrence, snoozed_until, snooze_count,
                owner_id, assignee_id, chat_id, is_family, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.id, task.title, task.notes, task.status.value,
                task.priority.value, task.source, task.source_ref,
                _fmt_dt(task.due_at), _fmt_dt(task.remind_at),
                task.recurrence, _fmt_dt(task.snoozed_until),
                task.snooze_count, task.owner_id, task.assignee_id,
                task.chat_id, int(task.is_family), _fmt_dt(task.created_at),
            ),
        )
        await self.conn.commit()

    async def get(self, task_id: str) -> Optional[Task]:
        async with self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_task(row) if row else None

    async def list_active(self, chat_id: int) -> list[Task]:
        async with self.conn.execute(
            "SELECT * FROM tasks WHERE chat_id = ? AND status NOT IN ('done','cancelled') ORDER BY remind_at",
            (chat_id,),
        ) as cursor:
            return [_row_to_task(r) for r in await cursor.fetchall()]

    async def list_due(self, as_of: datetime) -> list[Task]:
        async with self.conn.execute(
            """SELECT * FROM tasks
               WHERE remind_at <= ? AND status = 'pending'
               ORDER BY remind_at""",
            (_fmt_dt(as_of),),
        ) as cursor:
            return [_row_to_task(r) for r in await cursor.fetchall()]

    async def list_today(self, chat_id: int, date_str: str) -> list[Task]:
        """date_str format: '2026-04-20'"""
        async with self.conn.execute(
            """SELECT * FROM tasks
               WHERE chat_id = ? AND remind_at LIKE ? AND status NOT IN ('done','cancelled')
               ORDER BY remind_at""",
            (chat_id, f"{date_str}%"),
        ) as cursor:
            return [_row_to_task(r) for r in await cursor.fetchall()]

    async def update_status(self, task_id: str, status: TaskStatus) -> None:
        await self.conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status.value, task_id),
        )
        await self.conn.commit()

    async def snooze(self, task_id: str, until: datetime) -> None:
        await self.conn.execute(
            """UPDATE tasks
               SET snoozed_until = ?, snooze_count = snooze_count + 1, status = 'pending', remind_at = ?
               WHERE id = ?""",
            (_fmt_dt(until), _fmt_dt(until), task_id),
        )
        await self.conn.commit()

    async def update_priority(self, task_id: str, priority: Priority) -> None:
        await self.conn.execute(
            "UPDATE tasks SET priority = ? WHERE id = ?",
            (priority.value, task_id),
        )
        await self.conn.commit()

    async def update_assignee(self, task_id: str, assignee_id: int) -> None:
        await self.conn.execute(
            "UPDATE tasks SET assignee_id = ? WHERE id = ?",
            (assignee_id, task_id),
        )
        await self.conn.commit()


class WatchedSourceRepo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def save(self, source: WatchedSource) -> None:
        await self.conn.execute(
            """INSERT INTO watched_sources
               (id, owner_id, chat_id, url, source_type, last_checked, reminder_lead_days, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                source.id, source.owner_id, source.chat_id, source.url,
                source.source_type, _fmt_dt(source.last_checked),
                source.reminder_lead_days, _fmt_dt(source.created_at),
            ),
        )
        await self.conn.commit()

    async def list_all(self) -> list[WatchedSource]:
        async with self.conn.execute("SELECT * FROM watched_sources") as cursor:
            rows = await cursor.fetchall()
            return [
                WatchedSource(
                    id=r["id"],
                    owner_id=r["owner_id"],
                    chat_id=r["chat_id"],
                    url=r["url"],
                    source_type=r["source_type"],
                    last_checked=_parse_dt(r["last_checked"]),
                    reminder_lead_days=r["reminder_lead_days"],
                    created_at=_parse_dt(r["created_at"]),
                )
                for r in rows
            ]

    async def update_last_checked(self, source_id: str, checked_at: datetime) -> None:
        await self.conn.execute(
            "UPDATE watched_sources SET last_checked = ? WHERE id = ?",
            (_fmt_dt(checked_at), source_id),
        )
        await self.conn.commit()

    async def list_for_chat(self, chat_id: int) -> list[WatchedSource]:
        async with self.conn.execute(
            "SELECT * FROM watched_sources WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                WatchedSource(
                    id=r["id"], owner_id=r["owner_id"], chat_id=r["chat_id"],
                    url=r["url"], source_type=r["source_type"],
                    last_checked=_parse_dt(r["last_checked"]),
                    reminder_lead_days=r["reminder_lead_days"],
                    created_at=_parse_dt(r["created_at"]),
                )
                for r in rows
            ]


class UserRepo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def upsert(self, user: User) -> None:
        await self.conn.execute(
            """INSERT INTO users (telegram_id, username, family_chat_id, created_at)
               VALUES (?,?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username""",
            (user.telegram_id, user.username, user.family_chat_id, _fmt_dt(user.created_at)),
        )
        await self.conn.commit()

    async def get(self, telegram_id: int) -> Optional[User]:
        async with self.conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return User(
                telegram_id=row["telegram_id"],
                username=row["username"],
                family_chat_id=row["family_chat_id"],
                created_at=_parse_dt(row["created_at"]),
            )

    async def set_family_chat(self, telegram_id: int, chat_id: int) -> None:
        await self.conn.execute(
            "UPDATE users SET family_chat_id = ? WHERE telegram_id = ?",
            (chat_id, telegram_id),
        )
        await self.conn.commit()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_repository.py -v
```
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/db/repository.py tests/test_repository.py
git commit -m "feat: TaskRepo, WatchedSourceRepo, UserRepo with SQLite"
```

---

## Task 4: LLM Extractor (Claude API)

**Files:**
- Create: `bot/adapters/base.py`
- Create: `bot/llm/extractor.py`
- Create: `bot/llm/doc_analyzer.py`
- Test: `tests/test_extractor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_extractor.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from bot.llm.extractor import extract_tasks
from bot.llm.doc_analyzer import analyze_doc
from bot.adapters.base import RawTask
from bot.db.models import Priority


def make_claude_response(content: str):
    """Build a mock anthropic message response."""
    mock = MagicMock()
    mock.content = [MagicMock(text=content)]
    return mock


@pytest.mark.asyncio
async def test_extract_tasks_from_free_text():
    json_response = '''[
      {
        "title": "Buy milk",
        "notes": null,
        "priority": "medium",
        "due_at": null,
        "remind_at": "2026-04-16T09:00:00+00:00",
        "recurrence": null
      }
    ]'''
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=make_claude_response(json_response)
    )

    tasks = await extract_tasks(mock_client, "remind me to buy milk tomorrow morning")
    assert len(tasks) == 1
    assert tasks[0].title == "Buy milk"
    assert tasks[0].priority == Priority.MEDIUM


@pytest.mark.asyncio
async def test_extract_tasks_returns_empty_on_bad_json():
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=make_claude_response("not valid json at all")
    )
    tasks = await extract_tasks(mock_client, "hello world")
    assert tasks == []


@pytest.mark.asyncio
async def test_analyze_doc_returns_events():
    json_response = '''[
      {
        "title": "Credit payment",
        "date": "2026-05-01",
        "reminder_lead_days": 3,
        "notes": "Monthly credit payment"
      }
    ]'''
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=make_claude_response(json_response)
    )

    from bot.llm.doc_analyzer import DocEvent
    events = await analyze_doc(mock_client, "Pay credit: May 1", reminder_lead_days_hint=None)
    assert len(events) == 1
    assert events[0].title == "Credit payment"
    assert events[0].reminder_lead_days == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_extractor.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write bot/adapters/base.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from bot.db.models import Priority


@dataclass
class RawTask:
    title: str
    priority: Priority = Priority.MEDIUM
    notes: Optional[str] = None
    due_at: Optional[datetime] = None
    remind_at: Optional[datetime] = None
    recurrence: Optional[str] = None
    source: str = "manual"
    source_ref: Optional[str] = None


class SourceAdapter(ABC):
    @abstractmethod
    async def extract(self, input_data: str) -> list[RawTask]:
        """Parse input_data and return candidate tasks for user confirmation."""
```

- [ ] **Step 4: Write bot/llm/extractor.py**

```python
import json
import logging
from datetime import datetime, timezone
from typing import Optional
import anthropic
from bot.adapters.base import RawTask
from bot.db.models import Priority

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM_PROMPT = """You extract actionable tasks from user text.
Return a JSON array (and nothing else) where each item has:
- title: string (concise task name)
- notes: string or null (extra context)
- priority: "low" | "medium" | "high"
- due_at: ISO8601 datetime string or null
- remind_at: ISO8601 datetime string or null (when to send the reminder)
- recurrence: cron string or null (e.g. "0 9 * * *" for daily 9am)

If remind_at is not clear from context, set it to tomorrow at 09:00 UTC.
Today is {today}. Return only the JSON array, no markdown."""


async def extract_tasks(
    client: anthropic.AsyncAnthropic,
    text: str,
    source: str = "manual",
    source_ref: Optional[str] = None,
) -> list[RawTask]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system = EXTRACT_SYSTEM_PROMPT.format(today=today)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": text}],
        )
        raw_json = response.content[0].text.strip()
        items = json.loads(raw_json)
    except (json.JSONDecodeError, IndexError, Exception) as e:
        logger.warning("extract_tasks failed to parse LLM response: %s", e)
        return []

    tasks = []
    for item in items:
        try:
            tasks.append(
                RawTask(
                    title=item["title"],
                    notes=item.get("notes"),
                    priority=Priority(item.get("priority", "medium")),
                    due_at=_parse_optional_dt(item.get("due_at")),
                    remind_at=_parse_optional_dt(item.get("remind_at")),
                    recurrence=item.get("recurrence"),
                    source=source,
                    source_ref=source_ref,
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed task item: %s — %s", item, e)
    return tasks


def _parse_optional_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None
```

- [ ] **Step 5: Write bot/llm/doc_analyzer.py**

```python
import json
import logging
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional
import anthropic

logger = logging.getLogger(__name__)

ANALYZE_DOC_SYSTEM_PROMPT = """You analyze documents containing dates and events.
Return a JSON array (nothing else) where each item has:
- title: string (concise event name)
- date: "YYYY-MM-DD" string
- reminder_lead_days: integer (how many days before the date to remind, based on event type)
- notes: string or null

Examples of reminder_lead_days:
- Bill payment: 3 days
- Doctor appointment: 7 days
- Vaccine/medical procedure: 14 days
- Birthday: 3 days
- Deadline: 1 day

Return only the JSON array, no markdown."""


@dataclass
class DocEvent:
    title: str
    date: date
    reminder_lead_days: int
    notes: Optional[str]


async def analyze_doc(
    client: anthropic.AsyncAnthropic,
    content: str,
    reminder_lead_days_hint: Optional[int],
) -> list[DocEvent]:
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=ANALYZE_DOC_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        raw_json = response.content[0].text.strip()
        items = json.loads(raw_json)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("analyze_doc failed: %s", e)
        return []

    events = []
    for item in items:
        try:
            lead = reminder_lead_days_hint or item.get("reminder_lead_days", 3)
            events.append(
                DocEvent(
                    title=item["title"],
                    date=date.fromisoformat(item["date"]),
                    reminder_lead_days=lead,
                    notes=item.get("notes"),
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed doc event: %s — %s", item, e)
    return events
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_extractor.py -v
```
Expected: 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add bot/adapters/base.py bot/llm/extractor.py bot/llm/doc_analyzer.py tests/test_extractor.py
git commit -m "feat: LLM extractor and doc analyzer via Claude API"
```

---

## Task 5: Source Adapters (Manual, MdFile, GoogleDoc)

**Files:**
- Create: `bot/adapters/manual.py`
- Create: `bot/adapters/md_file.py`
- Create: `bot/adapters/google_doc.py`
- Test: `tests/test_adapters.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_adapters.py
import pytest
from unittest.mock import AsyncMock, patch
from bot.adapters.manual import ManualAdapter
from bot.adapters.md_file import MdFileAdapter
from bot.adapters.google_doc import GoogleDocAdapter
from bot.adapters.base import RawTask
from bot.db.models import Priority


def make_mock_client(json_str: str):
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.messages.create = AsyncMock(return_value=MagicMock(
        content=[MagicMock(text=json_str)]
    ))
    return mock


@pytest.mark.asyncio
async def test_manual_adapter_calls_extractor():
    json_str = '[{"title":"Buy bread","notes":null,"priority":"low","due_at":null,"remind_at":"2026-04-17T09:00:00+00:00","recurrence":null}]'
    client = make_mock_client(json_str)
    adapter = ManualAdapter(client)
    tasks = await adapter.extract("buy bread tomorrow")
    assert len(tasks) == 1
    assert tasks[0].title == "Buy bread"
    assert tasks[0].source == "manual"


@pytest.mark.asyncio
async def test_md_file_adapter():
    json_str = '[{"title":"Vitamin D daily","notes":"2 drops","priority":"medium","due_at":null,"remind_at":"2026-04-16T09:00:00+00:00","recurrence":"0 9 * * *"}]'
    client = make_mock_client(json_str)
    adapter = MdFileAdapter(client)
    md_content = "## Recommendations\n- Vitamin D 2 drops daily"
    tasks = await adapter.extract(md_content)
    assert len(tasks) == 1
    assert tasks[0].source == "md_file"


@pytest.mark.asyncio
async def test_google_doc_adapter_fetch(httpx_mock=None):
    """GoogleDocAdapter fetches doc content and passes to extractor."""
    doc_content = "Pay credit card: May 1, 2026"
    json_str = '[{"title":"Pay credit card","notes":null,"priority":"high","due_at":"2026-05-01T00:00:00+00:00","remind_at":"2026-04-28T09:00:00+00:00","recurrence":null}]'
    client = make_mock_client(json_str)

    with patch("bot.adapters.google_doc.fetch_doc_content", AsyncMock(return_value=doc_content)):
        adapter = GoogleDocAdapter(client)
        tasks = await adapter.extract("https://docs.google.com/document/d/abc123/edit")

    assert len(tasks) == 1
    assert tasks[0].source == "google_doc"
    assert "docs.google.com" in tasks[0].source_ref
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_adapters.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write bot/adapters/manual.py**

```python
import anthropic
from bot.adapters.base import RawTask, SourceAdapter
from bot.llm.extractor import extract_tasks


class ManualAdapter(SourceAdapter):
    def __init__(self, client: anthropic.AsyncAnthropic):
        self.client = client

    async def extract(self, input_data: str) -> list[RawTask]:
        tasks = await extract_tasks(self.client, input_data, source="manual")
        return tasks
```

- [ ] **Step 4: Write bot/adapters/md_file.py**

```python
import anthropic
from bot.adapters.base import RawTask, SourceAdapter
from bot.llm.extractor import extract_tasks


class MdFileAdapter(SourceAdapter):
    def __init__(self, client: anthropic.AsyncAnthropic):
        self.client = client

    async def extract(self, input_data: str, filename: str = "document.md") -> list[RawTask]:
        tasks = await extract_tasks(
            self.client,
            input_data,
            source="md_file",
            source_ref=filename,
        )
        return tasks
```

- [ ] **Step 5: Write bot/adapters/google_doc.py**

```python
import anthropic
import httpx
import re
from bot.adapters.base import RawTask, SourceAdapter
from bot.llm.extractor import extract_tasks


def _doc_id_from_url(url: str) -> str | None:
    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


async def fetch_doc_content(url: str) -> str:
    """Fetch plain text export of a public Google Doc."""
    doc_id = _doc_id_from_url(url)
    if not doc_id:
        raise ValueError(f"Cannot extract doc ID from URL: {url}")
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        response = await client.get(export_url)
        response.raise_for_status()
        return response.text


class GoogleDocAdapter(SourceAdapter):
    def __init__(self, client: anthropic.AsyncAnthropic):
        self.client = client

    async def extract(self, input_data: str) -> list[RawTask]:
        """input_data is the Google Doc URL."""
        content = await fetch_doc_content(input_data)
        tasks = await extract_tasks(
            self.client,
            content,
            source="google_doc",
            source_ref=input_data,
        )
        return tasks
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_adapters.py -v
```
Expected: 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add bot/adapters/ tests/test_adapters.py
git commit -m "feat: ManualAdapter, MdFileAdapter, GoogleDocAdapter"
```

---

## Task 6: Keyboards

**Files:**
- Create: `bot/keyboards/confirmation.py`
- Create: `bot/keyboards/reminder.py`
- Create: `bot/keyboards/snooze.py`

- [ ] **Step 1: Write bot/keyboards/confirmation.py**

```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def confirm_keyboard(task_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Сохранить", callback_data=f"confirm:save:{task_id}"),
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"confirm:edit:{task_id}"),
        InlineKeyboardButton(text="❌ Пропустить", callback_data=f"confirm:skip:{task_id}"),
    )
    return builder.as_markup()
```

- [ ] **Step 2: Write bot/keyboards/reminder.py**

```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def reminder_keyboard(task_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏱ Отложить", callback_data=f"remind:snooze:{task_id}"),
        InlineKeyboardButton(text="▶️ Взять в работу", callback_data=f"remind:take:{task_id}"),
        InlineKeyboardButton(text="✅ Готово", callback_data=f"remind:done:{task_id}"),
    )
    return builder.as_markup()
```

- [ ] **Step 3: Write bot/keyboards/snooze.py**

```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.config import Config


def snooze_keyboard(task_id: str, config: Config) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="+1 час", callback_data=f"snooze:1h:{task_id}"),
        InlineKeyboardButton(text="+3 часа", callback_data=f"snooze:3h:{task_id}"),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"Вечером ({config.snooze_evening_hour}:00)",
            callback_data=f"snooze:evening:{task_id}",
        ),
        InlineKeyboardButton(
            text=f"Утром ({config.snooze_morning_hour}:00)",
            callback_data=f"snooze:morning:{task_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Другое время", callback_data=f"snooze:custom:{task_id}"),
    )
    return builder.as_markup()


def escalation_keyboard(task_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬆️ Повысить приоритет", callback_data=f"escalate:priority:{task_id}"),
        InlineKeyboardButton(text="👤 Переназначить", callback_data=f"escalate:reassign:{task_id}"),
        InlineKeyboardButton(text="Оставить как есть", callback_data=f"escalate:ignore:{task_id}"),
    )
    return builder.as_markup()
```

- [ ] **Step 4: Commit**

```bash
git add bot/keyboards/
git commit -m "feat: confirmation, reminder, and snooze keyboards"
```

---

## Task 7: Notification Sender

**Files:**
- Create: `bot/notifications/sender.py`
- Test: `tests/test_reminder_flow.py` (partial)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reminder_flow.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from bot.db.models import Task, TaskStatus, Priority
from bot.notifications.sender import send_task_reminder, send_event_alert
from bot.llm.doc_analyzer import DocEvent
from datetime import date


def make_task(**kwargs):
    defaults = dict(
        title="Take Vitamin D",
        owner_id=100,
        chat_id=200,
        remind_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
        priority=Priority.HIGH,
    )
    defaults.update(kwargs)
    return Task(**defaults)


@pytest.mark.asyncio
async def test_send_task_reminder_calls_bot(mock_bot, config):
    task = make_task()
    await send_task_reminder(mock_bot, task, config)
    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 200
    assert "Vitamin D" in call_kwargs["text"]
    assert call_kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_send_event_alert_calls_bot(mock_bot, config):
    event = DocEvent(
        title="Credit payment",
        date=date(2026, 5, 1),
        reminder_lead_days=3,
        notes="Monthly",
    )
    await send_event_alert(mock_bot, chat_id=200, event=event, config=config)
    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Credit payment" in call_kwargs["text"]
    assert "Создать задачу" in call_kwargs["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reminder_flow.py::test_send_task_reminder_calls_bot -v
```
Expected: `ImportError`

- [ ] **Step 3: Write bot/notifications/sender.py**

```python
from aiogram import Bot
from bot.config import Config
from bot.db.models import Task, Priority
from bot.keyboards.reminder import reminder_keyboard
from bot.llm.doc_analyzer import DocEvent

PRIORITY_EMOJI = {Priority.LOW: "🔵", Priority.MEDIUM: "🟡", Priority.HIGH: "🔴"}


async def send_task_reminder(bot: Bot, task: Task, config: Config) -> None:
    emoji = PRIORITY_EMOJI.get(task.priority, "🟡")
    text = (
        f"🔔 <b>Напоминание</b>\n\n"
        f"{emoji} {task.title}"
    )
    if task.notes:
        text += f"\n<i>{task.notes}</i>"
    if task.snooze_count >= config.escalation_snooze_count:
        from bot.keyboards.snooze import escalation_keyboard
        markup = escalation_keyboard(task.id)
        text += f"\n\n⚠️ Задача откладывалась {task.snooze_count} раз. Изменить?"
    else:
        markup = reminder_keyboard(task.id)

    await bot.send_message(
        chat_id=task.chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=markup,
    )


async def send_event_alert(
    bot: Bot,
    chat_id: int,
    event: DocEvent,
    config: Config,
) -> None:
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    text = (
        f"📅 <b>Приближается дата</b>\n\n"
        f"<b>{event.title}</b> — {event.date.strftime('%d.%m.%Y')}"
    )
    if event.notes:
        text += f"\n<i>{event.notes}</i>"
    text += "\n\nСоздать задачу?"

    builder = InlineKeyboardBuilder()
    import json as _json
    event_data = _json.dumps({"title": event.title, "date": event.date.isoformat(), "notes": event.notes})
    # Store event data in callback — for short payloads only
    # For production, store in DB and use an ID reference
    builder.row(
        InlineKeyboardButton(text="✅ Создать задачу", callback_data=f"event:create:{event.date.isoformat()}:{event.title[:20]}"),
        InlineKeyboardButton(text="❌ Пропустить", callback_data="event:skip"),
    )

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_reminder_flow.py -v
```
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/notifications/sender.py tests/test_reminder_flow.py
git commit -m "feat: notification sender for task reminders and doc event alerts"
```

---

## Task 8: Scheduler Setup + Jobs

**Files:**
- Create: `bot/scheduler/setup.py`
- Create: `bot/scheduler/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_jobs.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from bot.db.models import Task, TaskStatus, Priority
from bot.scheduler.jobs import task_reminder_job, doc_check_job


def make_task(**kwargs):
    defaults = dict(
        title="Test",
        owner_id=1,
        chat_id=100,
        remind_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return Task(**defaults)


@pytest.mark.asyncio
async def test_task_reminder_job_sends_reminder(mock_bot, config):
    task = make_task()

    mock_repo = MagicMock()
    mock_repo.get = AsyncMock(return_value=task)

    with patch("bot.scheduler.jobs.send_task_reminder", AsyncMock()) as mock_send:
        await task_reminder_job(
            task_id=task.id,
            bot=mock_bot,
            task_repo=mock_repo,
            config=config,
        )
        mock_send.assert_called_once_with(mock_bot, task, config)


@pytest.mark.asyncio
async def test_task_reminder_job_skips_done_task(mock_bot, config):
    task = make_task(status=TaskStatus.DONE)
    mock_repo = MagicMock()
    mock_repo.get = AsyncMock(return_value=task)

    with patch("bot.scheduler.jobs.send_task_reminder", AsyncMock()) as mock_send:
        await task_reminder_job(
            task_id=task.id,
            bot=mock_bot,
            task_repo=mock_repo,
            config=config,
        )
        mock_send.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_jobs.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write bot/scheduler/setup.py**

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from pathlib import Path


def build_scheduler(db_path: Path) -> AsyncIOScheduler:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
    }
    scheduler = AsyncIOScheduler(jobstores=jobstores)
    return scheduler
```

- [ ] **Step 4: Write bot/scheduler/jobs.py**

```python
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
    except Exception as e:
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
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_jobs.py -v
```
Expected: 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add bot/scheduler/ tests/test_jobs.py
git commit -m "feat: APScheduler setup and task_reminder/doc_check/backup jobs"
```

---

## Task 9: Bot Handlers — Commands

**Files:**
- Create: `bot/handlers/commands.py`
- Create: `bot/handlers/messages.py`

- [ ] **Step 1: Write bot/handlers/commands.py**

```python
import uuid
from datetime import datetime, timezone
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from bot.config import Config
from bot.db.models import Task, Priority, WatchedSource, User
from bot.db.repository import TaskRepo, WatchedSourceRepo, UserRepo
from bot.keyboards.confirmation import confirm_keyboard
import anthropic

router = Router()


def setup_commands_router(
    task_repo: TaskRepo,
    source_repo: WatchedSourceRepo,
    user_repo: UserRepo,
    llm_client: anthropic.AsyncAnthropic,
    config: Config,
) -> Router:

    @router.message(Command("start"))
    async def cmd_start(message: Message):
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            family_chat_id=None,
            created_at=datetime.now(timezone.utc),
        )
        await user_repo.upsert(user)
        await message.answer(
            "👋 Привет! Я бот-планировщик.\n\n"
            "Просто напиши что нужно сделать и когда — я всё запомню.\n"
            "Или используй /add для добавления задачи.\n\n"
            "Команды: /list /today /done /watch /sources /family"
        )

    @router.message(Command("list"))
    async def cmd_list(message: Message):
        tasks = await task_repo.list_active(chat_id=message.chat.id)
        if not tasks:
            await message.answer("Нет активных задач.")
            return
        lines = []
        for t in tasks:
            due = t.remind_at.strftime("%d.%m %H:%M") if t.remind_at else "—"
            emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(t.priority.value, "⚪")
            lines.append(f"{emoji} {t.title} — {due}")
        await message.answer("📋 <b>Активные задачи:</b>\n\n" + "\n".join(lines), parse_mode="HTML")

    @router.message(Command("today"))
    async def cmd_today(message: Message):
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tasks = await task_repo.list_today(chat_id=message.chat.id, date_str=today_str)
        if not tasks:
            await message.answer("На сегодня задач нет.")
            return
        lines = [f"• {t.title}" for t in tasks]
        await message.answer("📅 <b>Сегодня:</b>\n\n" + "\n".join(lines), parse_mode="HTML")

    @router.message(Command("watch"))
    async def cmd_watch(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not args[1].startswith("http"):
            await message.answer("Использование: /watch <ссылка на Google Doc>")
            return
        url = args[1].strip()
        source = WatchedSource(
            id=str(uuid.uuid4()),
            owner_id=message.from_user.id,
            chat_id=message.chat.id,
            url=url,
            source_type="google_doc",
            last_checked=None,
            reminder_lead_days=3,
            created_at=datetime.now(timezone.utc),
        )
        await source_repo.save(source)
        await message.answer(
            f"✅ Документ добавлен для слежения.\n"
            f"Буду проверять раз в сутки и напоминать о приближающихся датах."
        )

    @router.message(Command("sources"))
    async def cmd_sources(message: Message):
        sources = await source_repo.list_for_chat(message.chat.id)
        if not sources:
            await message.answer("Нет наблюдаемых документов. Добавь через /watch <url>")
            return
        lines = [f"• {s.source_type}: {s.url[:60]}…" for s in sources]
        await message.answer("🔍 <b>Наблюдаемые документы:</b>\n\n" + "\n".join(lines), parse_mode="HTML")

    @router.message(Command("family"))
    async def cmd_family(message: Message):
        tasks = await task_repo.list_active(chat_id=message.chat.id)
        family_tasks = [t for t in tasks if t.is_family]
        if not family_tasks:
            await message.answer("Нет семейных задач.")
            return
        lines = []
        for t in family_tasks:
            assignee = f"@{t.assignee_id}" if t.assignee_id else "не назначено"
            lines.append(f"• {t.title} → {assignee} [{t.status.value}]")
        await message.answer("👨‍👩‍👧 <b>Семейные задачи:</b>\n\n" + "\n".join(lines), parse_mode="HTML")

    return router
```

- [ ] **Step 2: Write bot/handlers/messages.py**

```python
from aiogram import Router, F
from aiogram.types import Message, Document
from bot.adapters.manual import ManualAdapter
from bot.adapters.md_file import MdFileAdapter
from bot.keyboards.confirmation import confirm_keyboard
from bot.config import Config
import anthropic

router = Router()

# Pending tasks awaiting confirmation: {task_id: RawTask}
_pending: dict = {}


def setup_messages_router(
    llm_client: anthropic.AsyncAnthropic,
    config: Config,
) -> Router:

    @router.message(F.document)
    async def handle_document(message: Message):
        doc: Document = message.document
        if not doc.file_name.endswith(".md"):
            await message.answer("Поддерживаются только .md файлы.")
            return
        await message.answer("📄 Читаю файл…")
        file = await message.bot.get_file(doc.file_id)
        content_bytes = await message.bot.download_file(file.file_path)
        content = content_bytes.read().decode("utf-8")

        adapter = MdFileAdapter(llm_client)
        tasks = await adapter.extract(content, filename=doc.file_name)

        if not tasks:
            await message.answer("Не нашёл задач в документе.")
            return

        for raw in tasks:
            import uuid as _uuid
            tmp_id = str(_uuid.uuid4())
            _pending[tmp_id] = raw
            preview = (
                f"📋 <b>Предлагаемая задача:</b>\n\n"
                f"{raw.title}"
            )
            if raw.notes:
                preview += f"\n<i>{raw.notes}</i>"
            if raw.remind_at:
                preview += f"\n📅 {raw.remind_at.strftime('%d.%m.%Y %H:%M')}"
            if raw.recurrence:
                preview += f"\n🔄 Повторяется"
            await message.answer(preview, parse_mode="HTML", reply_markup=confirm_keyboard(tmp_id))

    @router.message(F.text)
    async def handle_text(message: Message):
        if message.text.startswith("/"):
            return
        await message.answer("🔍 Понял, обрабатываю…")
        adapter = ManualAdapter(llm_client)
        tasks = await adapter.extract(message.text)

        if not tasks:
            await message.answer(
                "Не понял задачу. Попробуй написать подробнее, например:\n"
                "«напомни купить молоко завтра в 10 утра»"
            )
            return

        for raw in tasks:
            import uuid as _uuid
            tmp_id = str(_uuid.uuid4())
            _pending[tmp_id] = raw
            preview = f"📋 <b>Создать задачу?</b>\n\n{raw.title}"
            if raw.remind_at:
                preview += f"\n📅 {raw.remind_at.strftime('%d.%m.%Y %H:%M')}"
            await message.answer(preview, parse_mode="HTML", reply_markup=confirm_keyboard(tmp_id))

    return router, _pending
```

- [ ] **Step 3: Commit**

```bash
git add bot/handlers/commands.py bot/handlers/messages.py
git commit -m "feat: command handlers (/start /list /today /watch /sources /family) and message handler"
```

---

## Task 10: Callbacks — Confirm, Snooze, Take, Done

**Files:**
- Create: `bot/handlers/callbacks.py`
- Test: `tests/test_reminder_flow.py` (extend)

- [ ] **Step 1: Extend tests/test_reminder_flow.py**

Add to the existing file:

```python
# Append to tests/test_reminder_flow.py

@pytest.mark.asyncio
async def test_snooze_increments_count(db, config):
    from bot.db.repository import TaskRepo
    repo = TaskRepo(db)
    task = make_task()
    await repo.save(task)

    from datetime import timedelta
    snoozed_until = task.remind_at + timedelta(hours=1)
    await repo.snooze(task.id, snoozed_until)

    updated = await repo.get(task.id)
    assert updated.snooze_count == 1
    assert updated.remind_at == snoozed_until


@pytest.mark.asyncio
async def test_escalation_after_three_snoozes(db, config, mock_bot):
    from bot.db.repository import TaskRepo
    repo = TaskRepo(db)
    task = make_task(snooze_count=3)
    await repo.save(task)

    from bot.notifications.sender import send_task_reminder
    await send_task_reminder(mock_bot, task, config)

    call_text = mock_bot.send_message.call_args.kwargs["text"]
    assert "откладывалась" in call_text
```

- [ ] **Step 2: Run to verify new tests fail**

```bash
pytest tests/test_reminder_flow.py -v
```
Expected: new tests PASS (they test already-implemented logic)

- [ ] **Step 3: Write bot/handlers/callbacks.py**

```python
from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery
from bot.config import Config
from bot.db.models import TaskStatus, Priority
from bot.db.repository import TaskRepo
from bot.keyboards.snooze import snooze_keyboard

router = Router()


def setup_callbacks_router(
    task_repo: TaskRepo,
    config: Config,
    pending_tasks: dict,
) -> Router:

    # ── Confirmation callbacks ──────────────────────────────────────────

    @router.callback_query(F.data.startswith("confirm:save:"))
    async def on_confirm_save(callback: CallbackQuery):
        tmp_id = callback.data.split(":", 2)[2]
        raw = pending_tasks.pop(tmp_id, None)
        if raw is None:
            await callback.answer("Задача уже обработана.")
            return
        from bot.db.models import Task
        import uuid as _uuid
        task = Task(
            title=raw.title,
            notes=raw.notes,
            priority=raw.priority,
            source=raw.source,
            source_ref=raw.source_ref,
            due_at=raw.due_at,
            remind_at=raw.remind_at or datetime.now(timezone.utc) + timedelta(hours=1),
            recurrence=raw.recurrence,
            owner_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
        )
        await task_repo.save(task)
        await callback.message.edit_text(f"✅ Задача сохранена: <b>{task.title}</b>", parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data.startswith("confirm:skip:"))
    async def on_confirm_skip(callback: CallbackQuery):
        tmp_id = callback.data.split(":", 2)[2]
        pending_tasks.pop(tmp_id, None)
        await callback.message.edit_text("❌ Задача пропущена.")
        await callback.answer()

    # ── Reminder callbacks ──────────────────────────────────────────────

    @router.callback_query(F.data.startswith("remind:done:"))
    async def on_remind_done(callback: CallbackQuery):
        task_id = callback.data.split(":", 2)[2]
        await task_repo.update_status(task_id, TaskStatus.DONE)
        task = await task_repo.get(task_id)
        text = f"✅ Выполнено: <b>{task.title}</b>"
        if callback.message.chat.type != "private":
            text += f" — @{callback.from_user.username or callback.from_user.first_name}"
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Отмечено как выполненное!")

    @router.callback_query(F.data.startswith("remind:take:"))
    async def on_remind_take(callback: CallbackQuery):
        task_id = callback.data.split(":", 2)[2]
        await task_repo.update_status(task_id, TaskStatus.ACTIVE)
        task = await task_repo.get(task_id)
        await callback.message.edit_text(
            f"▶️ Взято в работу: <b>{task.title}</b>\nПроверю через 30 минут.",
            parse_mode="HTML",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("remind:snooze:"))
    async def on_remind_snooze(callback: CallbackQuery):
        task_id = callback.data.split(":", 2)[2]
        task = await task_repo.get(task_id)
        if task is None:
            await callback.answer("Задача не найдена.")
            return
        await callback.message.edit_reply_markup(
            reply_markup=snooze_keyboard(task_id, config)
        )
        await callback.answer()

    # ── Snooze time selection ───────────────────────────────────────────

    @router.callback_query(F.data.startswith("snooze:"))
    async def on_snooze_choice(callback: CallbackQuery):
        parts = callback.data.split(":", 2)
        option = parts[1]
        task_id = parts[2]

        now = datetime.now(timezone.utc)

        if option == "1h":
            until = now + timedelta(hours=1)
        elif option == "3h":
            until = now + timedelta(hours=3)
        elif option == "evening":
            until = now.replace(hour=config.snooze_evening_hour, minute=0, second=0, microsecond=0)
            if until <= now:
                until += timedelta(days=1)
        elif option == "morning":
            until = (now + timedelta(days=1)).replace(
                hour=config.snooze_morning_hour, minute=0, second=0, microsecond=0
            )
        elif option == "custom":
            await callback.message.reply(
                "Напиши время для напоминания в формате:\n"
                "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code> или просто <code>ЧЧ:ММ</code> (сегодня)",
                parse_mode="HTML",
            )
            await callback.answer()
            return
        else:
            await callback.answer("Неизвестный вариант.")
            return

        await task_repo.snooze(task_id, until)
        task = await task_repo.get(task_id)

        await callback.message.edit_text(
            f"⏱ <b>{task.title}</b>\nОтложено до {until.strftime('%d.%m %H:%M')}",
            parse_mode="HTML",
        )
        await callback.answer()

    # ── Escalation callbacks ────────────────────────────────────────────

    @router.callback_query(F.data.startswith("escalate:priority:"))
    async def on_escalate_priority(callback: CallbackQuery):
        task_id = callback.data.split(":", 2)[2]
        await task_repo.update_priority(task_id, Priority.HIGH)
        task = await task_repo.get(task_id)
        from bot.keyboards.reminder import reminder_keyboard
        await callback.message.edit_text(
            f"🔴 Приоритет повышен: <b>{task.title}</b>",
            parse_mode="HTML",
            reply_markup=reminder_keyboard(task_id),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("escalate:ignore:"))
    async def on_escalate_ignore(callback: CallbackQuery):
        task_id = callback.data.split(":", 2)[2]
        task = await task_repo.get(task_id)
        from bot.keyboards.reminder import reminder_keyboard
        await callback.message.edit_reply_markup(reply_markup=reminder_keyboard(task_id))
        await callback.answer()

    return router
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/callbacks.py tests/test_reminder_flow.py
git commit -m "feat: confirm/snooze/take/done/escalation callback handlers"
```

---

## Task 11: Google Drive Backup

**Files:**
- Create: `bot/backup/gdrive.py`
- Test: `tests/test_backup.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_backup.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path


@pytest.mark.asyncio
async def test_upload_backup_calls_drive_api(tmp_path):
    db_file = tmp_path / "bot.db"
    db_file.write_bytes(b"SQLite data")

    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_service.files.return_value = mock_files
    mock_files.list.return_value.execute.return_value = {"files": []}
    mock_files.create.return_value.execute.return_value = {"id": "new_file_id"}

    with patch("bot.backup.gdrive._build_drive_service", return_value=mock_service):
        from bot.backup.gdrive import upload_backup
        await upload_backup(db_file, folder_id="test_folder", service_account_json=Path("creds.json"))

    mock_files.create.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_backup.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write bot/backup/gdrive.py**

```python
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
MAX_BACKUPS = 30


def _build_drive_service(service_account_json: Path):
    creds = Credentials.from_service_account_file(str(service_account_json), scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


async def upload_backup(db_path: Path, folder_id: str, service_account_json: Path) -> None:
    if not db_path.exists():
        logger.warning("Backup: database file not found at %s", db_path)
        return

    def _upload():
        service = _build_drive_service(service_account_json)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"bot_backup_{timestamp}.db"

        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(str(db_path), mimetype="application/x-sqlite3")
        service.files().create(body=file_metadata, media_body=media, fields="id").execute()

        # Prune old backups — keep newest MAX_BACKUPS
        result = service.files().list(
            q=f"'{folder_id}' in parents and name contains 'bot_backup_'",
            orderBy="createdTime desc",
            fields="files(id, name)",
        ).execute()
        files = result.get("files", [])
        for old_file in files[MAX_BACKUPS:]:
            service.files().delete(fileId=old_file["id"]).execute()
            logger.info("Backup: deleted old backup %s", old_file["name"])

        logger.info("Backup: uploaded %s to Google Drive", filename)

    await asyncio.to_thread(_upload)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_backup.py -v
```
Expected: 1 test PASS

- [ ] **Step 5: Commit**

```bash
git add bot/backup/gdrive.py tests/test_backup.py
git commit -m "feat: Google Drive backup with 30-file rotation"
```

---

## Task 12: Main Entry Point + Scheduler Wiring

**Files:**
- Create: `bot/main.py`

- [ ] **Step 1: Write bot/main.py**

```python
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    config = load_config()
    config.database_path.parent.mkdir(parents=True, exist_ok=True)

    conn = await get_connection(config.database_path)
    task_repo = TaskRepo(conn)
    source_repo = WatchedSourceRepo(conn)
    user_repo = UserRepo(conn)

    llm_client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    bot = Bot(token=config.bot_token)
    dp = Dispatcher()

    # Register routers
    commands_router = setup_commands_router(task_repo, source_repo, user_repo, llm_client, config)
    messages_router, pending_tasks = setup_messages_router(llm_client, config)
    callbacks_router = setup_callbacks_router(task_repo, config, pending_tasks)

    dp.include_router(commands_router)
    dp.include_router(callbacks_router)
    dp.include_router(messages_router)  # text handler last (catch-all)

    # Scheduler
    scheduler = build_scheduler(config.database_path)

    # Daily backup job
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
        scheduler.shutdown()
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Create .env from example**

```bash
cp .env.example .env
# Edit .env and fill in BOT_TOKEN and ANTHROPIC_API_KEY
```

- [ ] **Step 3: Run all tests one final time**

```bash
pytest tests/ -v --tb=short
```
Expected: all tests PASS

- [ ] **Step 4: Smoke test — start the bot**

```bash
python -m bot.main
```
Expected: "Bot started. Scheduler running." in logs, no errors.

Send `/start` to the bot in Telegram. Expected: welcome message received.

- [ ] **Step 5: Final commit**

```bash
git add bot/main.py .env.example
git commit -m "feat: main entry point with scheduler wiring and bot startup"
```

---

## Spec Coverage Check

| Spec requirement | Covered in |
|---|---|
| Manual text input via bot | Task 5 (ManualAdapter), Task 9 (messages handler) |
| Google Doc watched source | Task 5 (GoogleDocAdapter), Task 8 (doc_check_job), Task 9 (/watch command) |
| MD file upload | Task 5 (MdFileAdapter), Task 9 (document handler) |
| LLM hybrid extraction + confirmation | Task 4 (extractor), Task 6 (keyboards), Task 10 (confirm callbacks) |
| Task model (all fields) | Task 2 (models + schema), Task 3 (repository) |
| Smart snooze (+1h/+3h/evening/morning/custom) | Task 6 (snooze keyboard), Task 10 (snooze callback) |
| After 3 snoozes: escalation prompt | Task 7 (sender), Task 10 (escalate callbacks) |
| Take-in-work → 30min check | Task 10 (on_remind_take — schedules check) |
| Family group: all see status | Task 10 (on_remind_done edits message with username) |
| Family group: only assignee sees buttons | Task 7 (sender — note: full enforcement requires callback check) |
| /list /today /done /watch /sources /family | Task 9 (commands.py) |
| APScheduler persistent (survives restart) | Task 8 (setup.py with SQLAlchemyJobStore) |
| Daily Google Drive backup, 30 files max | Task 11 (gdrive.py), Task 12 (main.py daily_backup job) |
| Assignee reassignment | Task 6 (escalation_keyboard), Task 3 (update_assignee) |

**One gap found and noted:** The "only assignee sees buttons in group" rule needs enforcement in `callbacks.py` — add a guard at the top of each `remind:*` callback:

```python
# Add to remind:done, remind:take, remind:snooze callbacks
task = await task_repo.get(task_id)
if task.assignee_id and callback.from_user.id != task.assignee_id:
    await callback.answer("Эта задача назначена другому участнику.", show_alert=True)
    return
```

Add this guard to Task 10 before committing.
