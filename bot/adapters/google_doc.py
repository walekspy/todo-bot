import re
from typing import Optional
import anthropic
import httpx
from bot.adapters.base import RawTask, SourceAdapter
from bot.llm.extractor import extract_tasks


def _doc_id_from_url(url: str) -> Optional[str]:
    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


async def fetch_doc_content(url: str) -> str:
    """Fetch plain text export of a public Google Doc."""
    doc_id = _doc_id_from_url(url)
    if not doc_id:
        raise ValueError(f"Cannot extract doc ID from URL: {url}")
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        response = await client.get(export_url)
        response.raise_for_status()
        return response.text


class GoogleDocAdapter(SourceAdapter):
    def __init__(self, client: anthropic.AsyncAnthropic):
        self.client = client

    async def extract(self, input_data: str) -> list[RawTask]:
        """input_data is the Google Doc URL."""
        content = await fetch_doc_content(input_data)
        return await extract_tasks(
            self.client,
            content,
            source="google_doc",
            source_ref=input_data,
        )
