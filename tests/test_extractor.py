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


@pytest.mark.asyncio
async def test_extract_tasks_remind_at_parsed():
    """remind_at is correctly parsed as timezone-aware datetime."""
    json_response = '[{"title":"Buy milk","notes":null,"priority":"medium","due_at":null,"remind_at":"2026-04-16T09:00:00+00:00","recurrence":null}]'
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=make_claude_response(json_response))

    from datetime import timezone
    tasks = await extract_tasks(mock_client, "buy milk tomorrow")
    assert tasks[0].remind_at == datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_extract_tasks_skips_malformed_item():
    """Malformed items (missing title) are skipped, valid items returned."""
    json_response = '''[
      {"title": "Valid task", "priority": "low", "notes": null, "due_at": null, "remind_at": null, "recurrence": null},
      {"missing_title": true}
    ]'''
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=make_claude_response(json_response))

    tasks = await extract_tasks(mock_client, "some text")
    assert len(tasks) == 1
    assert tasks[0].title == "Valid task"


@pytest.mark.asyncio
async def test_analyze_doc_with_hint_overrides_llm():
    """reminder_lead_days_hint overrides LLM's suggestion."""
    json_response = '[{"title":"Pay bill","date":"2026-05-01","reminder_lead_days":7,"notes":null}]'
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=make_claude_response(json_response))

    events = await analyze_doc(mock_client, "Pay bill May 1", reminder_lead_days_hint=2)
    assert events[0].reminder_lead_days == 2  # hint overrides LLM's 7


@pytest.mark.asyncio
async def test_analyze_doc_hint_zero_is_valid():
    """reminder_lead_days_hint=0 means same-day reminder — must not be ignored."""
    json_response = '[{"title":"Event today","date":"2026-04-16","reminder_lead_days":3,"notes":null}]'
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=make_claude_response(json_response))

    events = await analyze_doc(mock_client, "event today", reminder_lead_days_hint=0)
    assert events[0].reminder_lead_days == 0  # 0 is a valid hint, not falsy skip
