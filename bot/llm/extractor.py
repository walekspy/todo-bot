import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, TYPE_CHECKING
import dateparser
from bot.adapters.base import RawTask
from bot.db.models import Priority

if TYPE_CHECKING:
    from bot.llm.client import LLMClient

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM_PROMPT = """You extract actionable tasks from user text.
Return a JSON array (and nothing else) where each item has:
- title: string (concise task name, keep original language)
- notes: string or null (extra context)
- priority: "low" | "medium" | "high"
- time_expression: string or null (extract ONLY the time/date value itself, without
  prepositions like "в", "на", "через". Examples:
  input "на 14:00" → "14:00",
  input "через 10 минут" → "через 10 минут",
  input "завтра в 10" → "завтра в 10",
  input "в пятницу" → "пятница",
  input "01.05 15:00" → "01.05 15:00",
  input "in 10 minutes" → "in 10 minutes",
  input "каждый день в 9" → "каждый день в 9".
  If no time mentioned, return null.)
- recurrence: cron string or null (e.g. "0 9 * * *" for daily 9am, null if not recurring)

Return only the JSON array, no markdown, no explanation."""


_LEADING_PREPS = ("в ", "на ", "во ", "к ", "до ")
_TIME_RE = re.compile(r'\b(\d{1,2}:\d{2})\b')
_HHMM_RE = re.compile(r'^(\d{1,2}):(\d{2})$')


def _strip_preposition(expr: str) -> str:
    """Remove a single leading Russian preposition from time expression."""
    low = expr.lower()
    for prep in _LEADING_PREPS:
        if low.startswith(prep):
            return expr[len(prep):]
    return expr


def _parse_time(expr: str, tz_name: str) -> Optional[datetime]:
    """Parse a natural-language time expression using dateparser."""
    expr = _strip_preposition(expr.strip())
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)

    # Fast path: bare HH:MM — dateparser is unreliable for this case
    m = _HHMM_RE.match(expr)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        candidate = now.replace(hour=h, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    result = dateparser.parse(
        expr,
        languages=["ru", "en"],
        settings={
            "TIMEZONE": tz_name,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": now,
            "PREFER_DAY_OF_MONTH": "first",
        },
    )
    return result


def _default_remind_at(tz_name: str) -> datetime:
    """Default reminder: tomorrow at 09:00 local time."""
    tz = ZoneInfo(tz_name)
    tomorrow = datetime.now(tz) + timedelta(days=1)
    return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)


async def extract_tasks(
    client: "LLMClient",
    text: str,
    source: str = "manual",
    source_ref: Optional[str] = None,
    tz_name: str = "UTC",
) -> list[RawTask]:
    try:
        raw_json = await client.complete(EXTRACT_SYSTEM_PROMPT, text)
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
            time_expr = item.get("time_expression")
            # Fallback: LLM missed the time but raw text has HH:MM
            if not time_expr:
                m = _TIME_RE.search(text)
                if m:
                    time_expr = m.group(1)
                    logger.debug("time_expression fallback from regex: %r", time_expr)
            if time_expr:
                remind_at = _parse_time(time_expr, tz_name)
                if remind_at is None:
                    logger.warning("dateparser could not parse: %r", time_expr)
                    remind_at = _default_remind_at(tz_name)
            else:
                remind_at = _default_remind_at(tz_name)

            tasks.append(
                RawTask(
                    title=item["title"],
                    notes=item.get("notes"),
                    priority=Priority(item.get("priority", "medium")),
                    due_at=remind_at,
                    remind_at=remind_at,
                    recurrence=item.get("recurrence"),
                    source=source,
                    source_ref=source_ref,
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed task item: %s — %s", item, e)
    return tasks
