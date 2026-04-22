import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta
from bot.llm.extractor import extract_tasks, _parse_time
from bot.llm.doc_analyzer import analyze_doc
from bot.adapters.base import RawTask
from bot.db.models import Priority


@pytest.mark.asyncio
async def test_extract_tasks_from_free_text():
    json_response = '[{"title":"Buy milk","notes":null,"priority":"medium","time_expression":"tomorrow at 9am","recurrence":null}]'
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(return_value=json_response)

    tasks = await extract_tasks(mock_client, "remind me to buy milk tomorrow morning", tz_name="UTC")
    assert len(tasks) == 1
    assert tasks[0].title == "Buy milk"
    assert tasks[0].priority == Priority.MEDIUM
    assert tasks[0].remind_at is not None


@pytest.mark.asyncio
async def test_extract_tasks_returns_empty_on_bad_json():
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(return_value="not valid json at all")
    tasks = await extract_tasks(mock_client, "hello world")
    assert tasks == []


@pytest.mark.asyncio
async def test_analyze_doc_returns_events():
    json_response = '[{"title":"Credit payment","date":"2026-05-01","reminder_lead_days":3,"notes":"Monthly credit payment"}]'
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(return_value=json_response)

    events = await analyze_doc(mock_client, "Pay credit: May 1", reminder_lead_days_hint=None)
    assert len(events) == 1
    assert events[0].title == "Credit payment"
    assert events[0].reminder_lead_days == 3


@pytest.mark.asyncio
async def test_extract_tasks_no_time_defaults_to_tomorrow():
    """If time_expression is null, remind_at defaults to tomorrow at 09:00."""
    json_response = '[{"title":"Buy milk","notes":null,"priority":"medium","time_expression":null,"recurrence":null}]'
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(return_value=json_response)

    tasks = await extract_tasks(mock_client, "buy milk", tz_name="UTC")
    assert len(tasks) == 1
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    assert tasks[0].remind_at.date() == tomorrow.date()
    assert tasks[0].remind_at.hour == 9


@pytest.mark.asyncio
async def test_extract_tasks_skips_malformed_item():
    """Malformed items (missing title) are skipped, valid items returned."""
    json_response = '[{"title":"Valid task","priority":"low","notes":null,"time_expression":null,"recurrence":null},{"missing_title":true}]'
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(return_value=json_response)

    tasks = await extract_tasks(mock_client, "some text")
    assert len(tasks) == 1
    assert tasks[0].title == "Valid task"


def test_parse_time_relative():
    """dateparser handles relative times correctly."""
    result = _parse_time("через 1 час", "UTC")
    assert result is not None
    now = datetime.now(timezone.utc)
    diff = (result - now).total_seconds()
    assert 3500 < diff < 3700  # ~1 hour


def test_parse_time_explicit():
    """dateparser handles explicit time."""
    result = _parse_time("2026-12-31 10:00", "UTC")
    assert result is not None
    assert result.month == 12
    assert result.day == 31
    assert result.hour == 10


def test_parse_time_invalid_returns_none():
    result = _parse_time("абракадабра xyz123", "UTC")
    assert result is None


def test_parse_time_bare_hhmm():
    """Bare 'HH:MM' is always resolved to a future datetime at that time."""
    result = _parse_time("12:50", "Asia/Vladivostok")
    assert result is not None
    assert result.hour == 12
    assert result.minute == 50
    # Must be in the future
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Vladivostok"))
    assert result > now


@pytest.mark.asyncio
async def test_extract_tasks_time_fallback_from_text():
    """If LLM returns time_expression=null but text has HH:MM, use regex fallback."""
    json_response = '[{"title":"проверка","notes":null,"priority":"medium","time_expression":null,"recurrence":null}]'
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(return_value=json_response)

    tasks = await extract_tasks(
        mock_client,
        "по просьбе добавь проверку на 12:50",
        tz_name="UTC",
    )
    assert len(tasks) == 1
    assert tasks[0].remind_at is not None
    assert tasks[0].remind_at.hour == 12
    assert tasks[0].remind_at.minute == 50


@pytest.mark.asyncio
async def test_analyze_doc_with_hint_overrides_llm():
    json_response = '[{"title":"Pay bill","date":"2026-05-01","reminder_lead_days":7,"notes":null}]'
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(return_value=json_response)

    events = await analyze_doc(mock_client, "Pay bill May 1", reminder_lead_days_hint=2)
    assert events[0].reminder_lead_days == 2


@pytest.mark.asyncio
async def test_analyze_doc_hint_zero_is_valid():
    json_response = '[{"title":"Event today","date":"2026-04-16","reminder_lead_days":3,"notes":null}]'
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(return_value=json_response)

    events = await analyze_doc(mock_client, "event today", reminder_lead_days_hint=0)
    assert events[0].reminder_lead_days == 0
