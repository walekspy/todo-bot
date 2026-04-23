import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from bot.db.models import Task, TaskStatus, Priority, WatchedSource, WatchedSheet, User, ChatMember, ChatSettings


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _row_to_task(row: aiosqlite.Row) -> Task:
    keys = row.keys()
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
        assignee_username=row["assignee_username"] if "assignee_username" in keys else None,
        notify_chat_id=row["notify_chat_id"] if "notify_chat_id" in keys else None,
        chat_id=row["chat_id"],
        is_family=bool(row["is_family"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]) if "updated_at" in keys else _parse_dt(row["created_at"]),
        google_task_id=row["google_task_id"] if "google_task_id" in keys else None,
        google_tasklist_id=row["google_tasklist_id"] if "google_tasklist_id" in keys else None,
        google_updated_at=_parse_dt(row["google_updated_at"]) if "google_updated_at" in keys else None,
    )


class TaskRepo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def save(self, task: Task) -> None:
        await self.conn.execute(
            """INSERT INTO tasks
               (id, title, notes, status, priority, source, source_ref,
                due_at, remind_at, recurrence, snoozed_until, snooze_count,
                owner_id, assignee_id, assignee_username, notify_chat_id,
                chat_id, is_family, created_at,
                updated_at, google_task_id, google_tasklist_id, google_updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.id, task.title, task.notes, task.status.value,
                task.priority.value, task.source, task.source_ref,
                _fmt_dt(task.due_at), _fmt_dt(task.remind_at),
                task.recurrence, _fmt_dt(task.snoozed_until),
                task.snooze_count, task.owner_id, task.assignee_id,
                task.assignee_username, task.notify_chat_id,
                task.chat_id, int(task.is_family),
                _fmt_dt(task.created_at), _fmt_dt(task.updated_at),
                task.google_task_id, task.google_tasklist_id, _fmt_dt(task.google_updated_at),
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

    async def list_today(self, chat_id: int, start: datetime, end: datetime) -> list[Task]:
        """Return non-done tasks for chat_id whose remind_at falls in [start, end)."""
        async with self.conn.execute(
            """SELECT * FROM tasks
               WHERE chat_id = ? AND remind_at >= ? AND remind_at < ?
                 AND status NOT IN ('done','cancelled')
               ORDER BY remind_at""",
            (chat_id, _fmt_dt(start), _fmt_dt(end)),
        ) as cursor:
            return [_row_to_task(r) for r in await cursor.fetchall()]

    async def update_status(self, task_id: str, status: TaskStatus) -> None:
        await self.conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, _fmt_dt(datetime.now(timezone.utc)), task_id),
        )
        await self.conn.commit()

    async def snooze(self, task_id: str, until: datetime) -> None:
        await self.conn.execute(
            """UPDATE tasks
               SET snoozed_until = ?, snooze_count = snooze_count + 1,
                   status = 'pending', remind_at = ?, updated_at = ?
               WHERE id = ?""",
            (_fmt_dt(until), _fmt_dt(until), _fmt_dt(datetime.now(timezone.utc)), task_id),
        )
        await self.conn.commit()

    async def update_priority(self, task_id: str, priority: Priority) -> None:
        await self.conn.execute(
            "UPDATE tasks SET priority = ?, updated_at = ? WHERE id = ?",
            (priority.value, _fmt_dt(datetime.now(timezone.utc)), task_id),
        )
        await self.conn.commit()

    async def get_by_google_id(self, google_task_id: str) -> Optional[Task]:
        async with self.conn.execute(
            "SELECT * FROM tasks WHERE google_task_id = ?", (google_task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_task(row) if row else None

    async def set_google_task_id(
        self, task_id: str, google_task_id: str,
        google_tasklist_id: str, google_updated_at: Optional[datetime]
    ) -> None:
        await self.conn.execute(
            """UPDATE tasks SET google_task_id = ?, google_tasklist_id = ?,
               google_updated_at = ? WHERE id = ?""",
            (google_task_id, google_tasklist_id,
             _fmt_dt(google_updated_at), task_id),
        )
        await self.conn.commit()

    async def update_from_google(
        self, task_id: str, title: str, notes: Optional[str],
        status: TaskStatus, due_at: Optional[datetime],
        remind_at: Optional[datetime],
        google_updated_at: Optional[datetime],
    ) -> None:
        await self.conn.execute(
            """UPDATE tasks SET title = ?, notes = ?, status = ?,
               due_at = ?, remind_at = ?, google_updated_at = ? WHERE id = ?""",
            (title, notes, status.value, _fmt_dt(due_at),
             _fmt_dt(remind_at), _fmt_dt(google_updated_at), task_id),
        )
        await self.conn.commit()

    async def list_all_active(self) -> list[Task]:
        """All non-cancelled tasks across all chats (for Google sync)."""
        async with self.conn.execute(
            "SELECT * FROM tasks WHERE status != 'cancelled' ORDER BY created_at"
        ) as cursor:
            return [_row_to_task(r) for r in await cursor.fetchall()]

    async def update_assignee(self, task_id: str, assignee_id: int) -> None:
        await self.conn.execute(
            "UPDATE tasks SET assignee_id = ? WHERE id = ?",
            (assignee_id, task_id),
        )
        await self.conn.commit()

    async def update_assignee_username(self, task_id: str, username: str) -> None:
        await self.conn.execute(
            "UPDATE tasks SET assignee_username = ? WHERE id = ?",
            (username, task_id),
        )
        await self.conn.commit()

    async def list_all_pending(self) -> list[Task]:
        """Return all non-terminal tasks with a future or past remind_at. Used on startup to reschedule."""
        async with self.conn.execute(
            "SELECT * FROM tasks WHERE status NOT IN ('done','cancelled') ORDER BY remind_at"
        ) as cursor:
            return [_row_to_task(r) for r in await cursor.fetchall()]


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

    async def delete(self, source_id: str) -> None:
        await self.conn.execute(
            "DELETE FROM watched_sources WHERE id = ?", (source_id,)
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


class WatchedSheetRepo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def save(self, sheet: WatchedSheet) -> None:
        await self.conn.execute(
            """INSERT OR REPLACE INTO watched_sheets
               (id, source_id, sheet_name, reminder_lead_days, enabled)
               VALUES (?,?,?,?,?)""",
            (sheet.id, sheet.source_id, sheet.sheet_name,
             sheet.reminder_lead_days, int(sheet.enabled)),
        )
        await self.conn.commit()

    async def save_many(self, sheets: list) -> None:
        for sheet in sheets:
            await self.conn.execute(
                """INSERT OR REPLACE INTO watched_sheets
                   (id, source_id, sheet_name, reminder_lead_days, enabled)
                   VALUES (?,?,?,?,?)""",
                (sheet.id, sheet.source_id, sheet.sheet_name,
                 sheet.reminder_lead_days, int(sheet.enabled)),
            )
        await self.conn.commit()

    async def list_for_source(self, source_id: str) -> list:
        async with self.conn.execute(
            "SELECT * FROM watched_sheets WHERE source_id = ? ORDER BY sheet_name",
            (source_id,)
        ) as cursor:
            return [
                WatchedSheet(
                    id=r["id"],
                    source_id=r["source_id"],
                    sheet_name=r["sheet_name"],
                    reminder_lead_days=r["reminder_lead_days"],
                    enabled=bool(r["enabled"]),
                )
                for r in await cursor.fetchall()
            ]

    async def get(self, sheet_id: str) -> Optional[WatchedSheet]:
        async with self.conn.execute(
            "SELECT * FROM watched_sheets WHERE id = ?", (sheet_id,)
        ) as cursor:
            r = await cursor.fetchone()
            if not r:
                return None
            return WatchedSheet(
                id=r["id"],
                source_id=r["source_id"],
                sheet_name=r["sheet_name"],
                reminder_lead_days=r["reminder_lead_days"],
                enabled=bool(r["enabled"]),
            )

    async def update_lead_days(self, sheet_id: str, days: int) -> None:
        await self.conn.execute(
            "UPDATE watched_sheets SET reminder_lead_days = ? WHERE id = ?",
            (days, sheet_id),
        )
        await self.conn.commit()

    async def delete_for_source(self, source_id: str) -> None:
        await self.conn.execute(
            "DELETE FROM watched_sheets WHERE source_id = ?", (source_id,)
        )
        await self.conn.commit()

    async def set_family_chat(self, telegram_id: int, chat_id: int) -> None:
        await self.conn.execute(
            "UPDATE users SET family_chat_id = ? WHERE telegram_id = ?",
            (chat_id, telegram_id),
        )
        await self.conn.commit()


class ChatSettingsRepo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def set_notify_chat(self, chat_id: int, notify_chat_id: int) -> None:
        await self.conn.execute(
            """INSERT INTO chat_settings (chat_id, notify_chat_id)
               VALUES (?,?)
               ON CONFLICT(chat_id) DO UPDATE SET notify_chat_id=excluded.notify_chat_id""",
            (chat_id, notify_chat_id),
        )
        await self.conn.commit()

    async def get(self, chat_id: int) -> Optional[ChatSettings]:
        async with self.conn.execute(
            "SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return ChatSettings(chat_id=row["chat_id"], notify_chat_id=row["notify_chat_id"])


class ChatMemberRepo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def upsert(self, member: ChatMember) -> None:
        await self.conn.execute(
            """INSERT INTO chat_members (chat_id, user_id, username, first_name)
               VALUES (?,?,?,?)
               ON CONFLICT(chat_id, user_id) DO UPDATE SET
                   username=excluded.username,
                   first_name=excluded.first_name""",
            (member.chat_id, member.user_id, member.username, member.first_name),
        )
        await self.conn.commit()

    async def list_for_chat(self, chat_id: int) -> list[ChatMember]:
        async with self.conn.execute(
            "SELECT * FROM chat_members WHERE chat_id = ? ORDER BY first_name",
            (chat_id,),
        ) as cursor:
            return [
                ChatMember(
                    chat_id=r["chat_id"],
                    user_id=r["user_id"],
                    username=r["username"],
                    first_name=r["first_name"],
                )
                for r in await cursor.fetchall()
            ]
