import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bot.adapters.manual import ManualAdapter
from bot.adapters.md_file import MdFileAdapter
from bot.adapters.google_doc import GoogleDocAdapter
from bot.adapters.base import RawTask
from bot.db.models import Priority


def make_mock_client(json_str: str):
    mock = AsyncMock()
    mock.complete = AsyncMock(return_value=json_str)
    return mock


@pytest.mark.asyncio
async def test_manual_adapter_calls_extractor():
    json_str = '[{"title":"Buy bread","notes":null,"priority":"low","time_expression":"tomorrow","recurrence":null}]'
    client = make_mock_client(json_str)
    adapter = ManualAdapter(client)
    tasks = await adapter.extract("buy bread tomorrow")
    assert len(tasks) == 1
    assert tasks[0].title == "Buy bread"
    assert tasks[0].source == "manual"


@pytest.mark.asyncio
async def test_md_file_adapter():
    json_str = '[{"title":"Vitamin D daily","notes":"2 drops","priority":"medium","time_expression":null,"recurrence":"0 9 * * *"}]'
    client = make_mock_client(json_str)
    adapter = MdFileAdapter(client)
    md_content = "## Recommendations\n- Vitamin D 2 drops daily"
    tasks = await adapter.extract(md_content)
    assert len(tasks) == 1
    assert tasks[0].source == "md_file"


@pytest.mark.asyncio
async def test_google_doc_adapter_fetch():
    doc_content = "Pay credit card: May 1, 2026"
    json_str = '[{"title":"Pay credit card","notes":null,"priority":"high","time_expression":"May 1 2026","recurrence":null}]'
    client = make_mock_client(json_str)

    with patch("bot.adapters.google_doc.fetch_doc_content", AsyncMock(return_value=doc_content)):
        adapter = GoogleDocAdapter(client)
        tasks = await adapter.extract("https://docs.google.com/document/d/abc123/edit")

    assert len(tasks) == 1
    assert tasks[0].source == "google_doc"
    assert "docs.google.com" in tasks[0].source_ref


@pytest.mark.asyncio
async def test_md_file_adapter_sets_source_ref():
    json_str = '[{"title":"T","notes":null,"priority":"medium","time_expression":null,"recurrence":null}]'
    client = make_mock_client(json_str)
    adapter = MdFileAdapter(client)
    tasks = await adapter.extract("content", filename="health.md")
    assert tasks[0].source_ref == "health.md"


@pytest.mark.asyncio
async def test_fetch_doc_content_raises_on_bad_url():
    from bot.adapters.google_doc import fetch_doc_content
    with pytest.raises(ValueError, match="Cannot extract doc ID"):
        await fetch_doc_content("https://example.com/not-a-doc")


@pytest.mark.asyncio
async def test_google_doc_adapter_propagates_fetch_error():
    client = make_mock_client("[]")
    with patch("bot.adapters.google_doc.fetch_doc_content", AsyncMock(side_effect=ValueError("HTTP 403"))):
        adapter = GoogleDocAdapter(client)
        with pytest.raises(ValueError):
            await adapter.extract("https://docs.google.com/document/d/abc/edit")
