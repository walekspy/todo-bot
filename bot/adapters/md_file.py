import anthropic
from bot.adapters.base import RawTask, SourceAdapter
from bot.llm.extractor import extract_tasks


class MdFileAdapter(SourceAdapter):
    def __init__(self, client: anthropic.AsyncAnthropic):
        self.client = client

    async def extract(self, input_data: str, filename: str = "document.md") -> list[RawTask]:
        return await extract_tasks(
            self.client,
            input_data,
            source="md_file",
            source_ref=filename,
        )
