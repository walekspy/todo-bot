import pytest
from unittest.mock import AsyncMock, MagicMock
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
