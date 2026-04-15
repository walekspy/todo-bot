import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bot.adapters.manual import ManualAdapter
from bot.adapters.md_file import MdFileAdapter
from bot.adapters.google_doc import GoogleDocAdapter
from bot.adapters.base import RawTask
from bot.db.models import Priority


def make_mock_client(json_str: str):
    mock = MagicMock()
    mock.messages.create = AsyncMock(return_value=MagicMock(
        content=[MagicMock(text=json_str)]
    ))
    return mock


@pytest.mark.asyncio
async def test_manual_adapter_calls_extractor():
    json_str = '[{"title":"Buy bread","notes":null,"priority":"low","due_at":null,"remind_at":"2026-04-17T09:00:00+00:00","recurrence":null}]'
    client = make_mock_client(json_str)
    adapter = ManualAdapter(client)
    tasks = await adapter.extract("buy bread tomorrow")
    assert len(tasks) == 1
    assert tasks[0].title == "Buy bread"
    assert tasks[0].source == "manual"


@pytest.mark.asyncio
async def test_md_file_adapter():
    json_str = '[{"title":"Vitamin D daily","notes":"2 drops","priority":"medium","due_at":null,"remind_at":"2026-04-16T09:00:00+00:00","recurrence":"0 9 * * *"}]'
    client = make_mock_client(json_str)
    adapter = MdFileAdapter(client)
    md_content = "## Recommendations\n- Vitamin D 2 drops daily"
    tasks = await adapter.extract(md_content)
    assert len(tasks) == 1
    assert tasks[0].source == "md_file"


@pytest.mark.asyncio
async def test_google_doc_adapter_fetch():
    doc_content = "Pay credit card: May 1, 2026"
    json_str = '[{"title":"Pay credit card","notes":null,"priority":"high","due_at":"2026-05-01T00:00:00+00:00","remind_at":"2026-04-28T09:00:00+00:00","recurrence":null}]'
    client = make_mock_client(json_str)

    with patch("bot.adapters.google_doc.fetch_doc_content", AsyncMock(return_value=doc_content)):
        adapter = GoogleDocAdapter(client)
        tasks = await adapter.extract("https://docs.google.com/document/d/abc123/edit")

    assert len(tasks) == 1
    assert tasks[0].source == "google_doc"
    assert "docs.google.com" in tasks[0].source_ref
