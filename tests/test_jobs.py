import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
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


@pytest.mark.asyncio
async def test_task_reminder_job_skips_missing_task(mock_bot, config):
    mock_repo = MagicMock()
    mock_repo.get = AsyncMock(return_value=None)

    with patch("bot.scheduler.jobs.send_task_reminder", AsyncMock()) as mock_send:
        await task_reminder_job(
            task_id="nonexistent-id",
            bot=mock_bot,
            task_repo=mock_repo,
            config=config,
        )
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_task_reminder_job_skips_snoozed_task(mock_bot, config):
    from datetime import timedelta
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    task = make_task(snoozed_until=future)
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


@pytest.mark.asyncio
async def test_doc_check_job_sends_alert_for_upcoming_event(mock_bot, config):
    from bot.db.models import WatchedSource
    from bot.llm.doc_analyzer import DocEvent
    from datetime import date, timedelta

    source = WatchedSource(owner_id=1, chat_id=100, url="https://docs.google.com/document/d/abc", source_type="google_doc")
    mock_source_repo = MagicMock()
    mock_source_repo.list_all = AsyncMock(return_value=[source])
    mock_source_repo.update_last_checked = AsyncMock()

    # Event 2 days away with lead=3 → should trigger
    upcoming = date.today() + timedelta(days=2)
    events = [DocEvent(title="Pay bill", date=upcoming, reminder_lead_days=3, notes=None)]

    mock_llm = MagicMock()

    with patch("bot.scheduler.jobs.fetch_doc_content", AsyncMock(return_value="doc content")), \
         patch("bot.scheduler.jobs.analyze_doc", AsyncMock(return_value=events)), \
         patch("bot.scheduler.jobs.send_event_alert", AsyncMock()) as mock_alert:
        await doc_check_job(
            source_id=source.id,
            bot=mock_bot,
            source_repo=mock_source_repo,
            llm_client=mock_llm,
            config=config,
        )
        mock_alert.assert_called_once()


@pytest.mark.asyncio
async def test_doc_check_job_skips_missing_source(mock_bot, config):
    mock_source_repo = MagicMock()
    mock_source_repo.list_all = AsyncMock(return_value=[])
    mock_llm = MagicMock()

    with patch("bot.scheduler.jobs.send_event_alert", AsyncMock()) as mock_alert:
        await doc_check_job(
            source_id="nonexistent",
            bot=mock_bot,
            source_repo=mock_source_repo,
            llm_client=mock_llm,
            config=config,
        )
        mock_alert.assert_not_called()
