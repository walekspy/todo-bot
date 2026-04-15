import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional
import anthropic

logger = logging.getLogger(__name__)

ANALYZE_DOC_SYSTEM_PROMPT = """You analyze documents containing dates and events.
Return a JSON array (nothing else) where each item has:
- title: string (concise event name)
- date: "YYYY-MM-DD" string
- reminder_lead_days: integer (how many days before the date to remind, based on event type)
- notes: string or null

Examples of reminder_lead_days:
- Bill payment: 3 days
- Doctor appointment: 7 days
- Vaccine/medical procedure: 14 days
- Birthday: 3 days
- Deadline: 1 day

Return only the JSON array, no markdown."""


@dataclass
class DocEvent:
    title: str
    date: date
    reminder_lead_days: int
    notes: Optional[str]


async def analyze_doc(
    client: anthropic.AsyncAnthropic,
    content: str,
    reminder_lead_days_hint: Optional[int],
) -> list[DocEvent]:
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=ANALYZE_DOC_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError as e:
        logger.error("analyze_doc: Claude API error: %s", e)
        raise

    try:
        raw_json = response.content[0].text.strip()
        items = json.loads(raw_json)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning("analyze_doc: unparseable LLM response: %s", e)
        return []

    events = []
    for item in items:
        try:
            # Use hint if explicitly provided (even 0 is valid), else use LLM value
            lead = item.get("reminder_lead_days", 3) if reminder_lead_days_hint is None else reminder_lead_days_hint
            events.append(
                DocEvent(
                    title=item["title"],
                    date=date.fromisoformat(item["date"]),
                    reminder_lead_days=lead,
                    notes=item.get("notes"),
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed doc event: %s — %s", item, e)
    return events
