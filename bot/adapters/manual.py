import anthropic
from bot.adapters.base import RawTask, SourceAdapter
from bot.llm.extractor import extract_tasks


class ManualAdapter(SourceAdapter):
    def __init__(self, client: anthropic.AsyncAnthropic):
        self.client = client

    async def extract(self, input_data: str) -> list[RawTask]:
        return await extract_tasks(self.client, input_data, source="manual")
