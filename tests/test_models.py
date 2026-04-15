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
