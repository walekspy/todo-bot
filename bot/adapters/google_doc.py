import re
from typing import Optional
from urllib.parse import urlparse
import anthropic
import httpx
from bot.adapters.base import RawTask, SourceAdapter
from bot.llm.extractor import extract_tasks


def _doc_id_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.netloc not in ("docs.google.com", "www.docs.google.com"):
        return None
    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", parsed.path)
    return match.group(1) if match else None


async def fetch_doc_content(url: str) -> str:
    """Fetch plain text export of a public Google Doc.

    Raises ValueError for bad URLs, inaccessible docs, and network errors.
    """
    doc_id = _doc_id_from_url(url)
    if not doc_id:
        raise ValueError(f"Cannot extract doc ID from URL: {url}")
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as client:
            response = await client.get(export_url)
            response.raise_for_status()
            return response.text
    except httpx.TimeoutException as e:
        raise ValueError(f"Timed out fetching Google Doc: {url}") from e
    except httpx.HTTPStatusError as e:
        raise ValueError(f"HTTP {e.response.status_code} fetching Google Doc: {url}") from e
    except httpx.RequestError as e:
        raise ValueError(f"Network error fetching Google Doc: {url}") from e


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
