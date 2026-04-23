import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from bot.db.models import Task, TaskStatus, Priority, WatchedSource, User
from bot.db.repository import TaskRepo, WatchedSourceRepo, UserRepo, ChatSettingsRepo
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


# ---- ChatSettingsRepo ----


@pytest.mark.asyncio
async def test_chat_settings_set_and_get(db):
    repo = ChatSettingsRepo(db)
    await repo.set_notify_chat(chat_id=100, notify_chat_id=500)
    settings = await repo.get(100)
    assert settings is not None
    assert settings.chat_id == 100
    assert settings.notify_chat_id == 500


@pytest.mark.asyncio
async def test_chat_settings_get_missing_returns_none(db):
    repo = ChatSettingsRepo(db)
    settings = await repo.get(999)
    assert settings is None


@pytest.mark.asyncio
async def test_chat_settings_set_overwrites(db):
    repo = ChatSettingsRepo(db)
    await repo.set_notify_chat(100, 500)
    await repo.set_notify_chat(100, 600)
    settings = await repo.get(100)
    assert settings.notify_chat_id == 600


@pytest.mark.asyncio
async def test_chat_settings_clear_removes_routing(db):
    repo = ChatSettingsRepo(db)
    await repo.set_notify_chat(100, 500)
    await repo.clear_notify_chat(100)
    settings = await repo.get(100)
    assert settings is None


@pytest.mark.asyncio
async def test_chat_settings_clear_missing_is_noop(db):
    repo = ChatSettingsRepo(db)
    # Should not raise when clearing a chat that has no settings
    await repo.clear_notify_chat(999)
    assert await repo.get(999) is None


@pytest.mark.asyncio
async def test_task_notify_chat_id_roundtrip(db):
    """Task with notify_chat_id should persist and load correctly."""
    repo = TaskRepo(db)
    task = make_task(title="Routed task", notify_chat_id=777)
    await repo.save(task)
    fetched = await repo.get(task.id)
    assert fetched.notify_chat_id == 777
