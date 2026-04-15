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
