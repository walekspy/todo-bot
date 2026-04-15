import aiosqlite
from datetime import datetime
from typing import Optional
from bot.db.models import Task, TaskStatus, Priority, WatchedSource, User


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
               WHERE remind_at <= ?
                 AND status = 'pending'
                 AND (snoozed_until IS NULL OR snoozed_until <= ?)
               ORDER BY remind_at""",
            (_fmt_dt(as_of), _fmt_dt(as_of)),
        ) as cursor:
            return [_row_to_task(r) for r in await cursor.fetchall()]

    async def list_today(self, chat_id: int, date_str: str) -> list[Task]:
        """Return non-done tasks for chat_id whose remind_at falls on date_str (UTC, format: YYYY-MM-DD)."""
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
