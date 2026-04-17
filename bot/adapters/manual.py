from typing import TYPE_CHECKING
from bot.adapters.base import RawTask, SourceAdapter
from bot.llm.extractor import extract_tasks

if TYPE_CHECKING:
    from bot.llm.client import LLMClient


class ManualAdapter(SourceAdapter):
    def __init__(self, client: "LLMClient"):
        self.client = client

    async def extract(self, input_data: str) -> list[RawTask]:
        return await extract_tasks(self.client, input_data, source="manual")
