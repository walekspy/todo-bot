import json
import logging
from datetime import datetime, timezone
from typing import Optional
import anthropic
from bot.adapters.base import RawTask
from bot.db.models import Priority

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM_PROMPT = """You extract actionable tasks from user text.
Return a JSON array (and nothing else) where each item has:
- title: string (concise task name)
- notes: string or null (extra context)
- priority: "low" | "medium" | "high"
- due_at: ISO8601 datetime string or null
- remind_at: ISO8601 datetime string or null (when to send the reminder)
- recurrence: cron string or null (e.g. "0 9 * * *" for daily 9am)

If remind_at is not clear from context, set it to tomorrow at 09:00 UTC.
Today is {today}. Return only the JSON array, no markdown."""


async def extract_tasks(
    client: anthropic.AsyncAnthropic,
    text: str,
    source: str = "manual",
    source_ref: Optional[str] = None,
) -> list[RawTask]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system = EXTRACT_SYSTEM_PROMPT.format(today=today)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": text}],
        )
        raw_json = response.content[0].text.strip()
        items = json.loads(raw_json)
    except (json.JSONDecodeError, IndexError, Exception) as e:
        logger.warning("extract_tasks failed to parse LLM response: %s", e)
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
