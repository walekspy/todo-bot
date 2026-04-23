import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, date
from bot.db.models import Task, TaskStatus, Priority
from bot.notifications.sender import send_task_reminder, send_event_alert
from bot.llm.doc_analyzer import DocEvent


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
async def test_send_task_reminder_sends_message(mock_bot, config):
    task = make_task()
    await send_task_reminder(mock_bot, task, config)
    mock_bot.send_message.assert_called_once()
    kwargs = mock_bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == 200
    assert "Vitamin D" in kwargs["text"]
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_send_task_reminder_escalation_after_snoozes(mock_bot, config):
    task = make_task(snooze_count=3)
    await send_task_reminder(mock_bot, task, config)
    kwargs = mock_bot.send_message.call_args.kwargs
    assert "откладывалась" in kwargs["text"]
    # escalation keyboard has escalate: prefix buttons
    markup = kwargs["reply_markup"]
    assert markup is not None
    first_button = markup.inline_keyboard[0][0]
    assert first_button.callback_data.startswith("escalate:")


@pytest.mark.asyncio
async def test_send_event_alert_sends_message(mock_bot, config):
    event = DocEvent(
        title="Credit payment",
        date=date(2026, 5, 1),
        reminder_lead_days=3,
        notes="Monthly",
    )
    await send_event_alert(mock_bot, chat_id=200, event=event, config=config)
    mock_bot.send_message.assert_called_once()
    kwargs = mock_bot.send_message.call_args.kwargs
    assert "Credit payment" in kwargs["text"]
    assert "Создать задачу" in kwargs["text"]


# ---- Dual-group reminder routing ----


@pytest.mark.asyncio
async def test_reminder_routes_to_notify_chat_when_set(mock_bot, config):
    """Task with notify_chat_id goes to that chat, not the creation chat."""
    task = make_task(chat_id=200, notify_chat_id=300)
    await send_task_reminder(mock_bot, task, config)
    kwargs = mock_bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == 300  # routed to notify_chat_id, not creation chat


@pytest.mark.asyncio
async def test_reminder_falls_back_to_chat_id_when_notify_none(mock_bot, config):
    """Task with no notify_chat_id falls back to creation chat."""
    task = make_task(chat_id=200, notify_chat_id=None)
    await send_task_reminder(mock_bot, task, config)
    kwargs = mock_bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == 200


@pytest.mark.asyncio
async def test_reminder_routes_to_notify_chat_for_escalation(mock_bot, config):
    """Even escalated reminders (snooze_count >= threshold) go to notify_chat_id."""
    task = make_task(chat_id=200, notify_chat_id=300, snooze_count=5)
    await send_task_reminder(mock_bot, task, config)
    kwargs = mock_bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == 300
    assert "откладывалась" in kwargs["text"]
