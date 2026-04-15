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
