import json
import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from bot.adapters.base import RawTask
from bot.db.models import Priority

if TYPE_CHECKING:
    from bot.llm.client import LLMClient

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM_PROMPT = """You extract actionable tasks from user text.
Return a JSON array (and nothing else) where each item has:
- title: string (concise task name)
- notes: string or null (extra context)
- priority: "low" | "medium" | "high"
- due_at: ISO8601 datetime string with UTC offset (e.g. 2026-04-16T09:00:00+00:00) or null
- remind_at: ISO8601 datetime string with UTC offset or null (when to send the reminder)
- recurrence: cron string or null (e.g. "0 9 * * *" for daily 9am)

If remind_at is not clear from context, set it to tomorrow at 09:00 UTC.
All datetimes MUST include a UTC offset (+00:00).
Today is {today}. Return only the JSON array, no markdown."""


async def extract_tasks(
    client: "LLMClient",
    text: str,
    source: str = "manual",
    source_ref: Optional[str] = None,
) -> list[RawTask]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system = EXTRACT_SYSTEM_PROMPT.format(today=today)

    try:
        raw_json = await client.complete(system, text)
    except Exception as e:
        logger.error("extract_tasks: LLM error: %s", e)
        raise

    try:
        items = json.loads(raw_json.strip())
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning("extract_tasks: unparseable LLM response: %s", e)
        return []

    tasks = []
    for item in items:
        try:
            tasks.append(
                RawTask(
                    title=item["title"],
                    notes=item.get("notes"),
                    priority=Priority(item.get("priority", "medium")),
                    due_at=_parse_optional_dt(item.get("due_at")),
                    remind_at=_parse_optional_dt(item.get("remind_at")),
                    recurrence=item.get("recurrence"),
                    source=source,
                    source_ref=source_ref,
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed task item: %s — %s", item, e)
    return tasks


def _parse_optional_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None
