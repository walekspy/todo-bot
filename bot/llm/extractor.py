import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, TYPE_CHECKING
import dateparser
from dateparser.search import search_dates
from bot.adapters.base import RawTask
from bot.db.models import Priority

if TYPE_CHECKING:
    from bot.llm.client import LLMClient

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM_PROMPT = """You extract TODO tasks from free-form Russian text. The text may contain speech-to-text errors — CORRECT them intelligently.

Your job:
1. UNDERSTAND what the user WANTS (ignore garbled STT artifacts)
2. Extract: what to do, when, how urgent, repeat schedule
3. Return a JSON array

Return EXACTLY a JSON array — nothing before, nothing after:
[
  {
    "title": "concise task in Russian, FIX STT errors: 'задание' not 'задать', 'задачу' not 'задать', 'в' noise words OK",
    "notes": "string or null",
    "priority": "low | medium | high (default medium)",
    "time_expression": "time or date+time in plain Russian, e.g. 'через 2 минуты', 'завтра в 14:00', 'через 5 минут'",
    "recurrence": "cron string or null"
  }
]

CORRECTION EXAMPLES:
- "задать" or "задать в" → "задачу"
- "завтрака" → "завтра"
- "память" → ignore as noise
- "вот поставь задать в через 2 минута" → title="задача", time_expression="через 2 минуты"
- "поставь напоминание через 2 минуты" → title="напоминание", time_expression="через 2 минуты"
- "напомни через 5 минут" → title="напоминание", time_expression="через 5 минут"
- NO task specified, only time like "через 3 минуты" → title="напоминание"

STT ARTIFACTS TO IGNORE: filler words like "вот", "ну", "типа", repeated words, partial words at boundaries.

Return ONLY the JSON array. No explanation, no chat, no "Готово"."""


_LEADING_PREPS = ("в ", "на ", "во ", "к ", "до ")
_TIME_RE = re.compile(r'\b(\d{1,2}:\d{2})\b')
_HHMM_RE = re.compile(r'^(\d{1,2}):(\d{2})$')

# Imperative patterns that confuse the LLM into acting like an assistant
_IMPERATIVE_RE = re.compile(
    r'^\s*(напомни|поставь\s+напоминание|поставь\s+задачу|'
    r'создай\s+напоминание|создай\s+задачу|'
    r'запланируй|добавь\s+задачу|добавь\s+напоминание|'
    r'напомнить|поставить\s+напоминание)\s+',
    re.IGNORECASE)


def _preprocess_text(text: str) -> str:
    """Light cleanup — strip leading @mention if present, keep everything else for LLM to interpret."""
    # Remove @botname at the start of the text (already handled in handler, but double-safe)
    text = re.sub(r'^@\w+\s+', '', text)
    # Remove common filler words at the START only, keep the rest for context
    text = re.sub(r'^(ну\s+|вот\s+|типа\s+|собственно\s+)+', '', text, flags=re.IGNORECASE)
    return text.strip()


def _strip_preposition(expr: str) -> str:
    """Remove a single leading Russian preposition from time expression."""
    low = expr.lower()
    for prep in _LEADING_PREPS:
        if low.startswith(prep):
            return expr[len(prep):]
    return expr


def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences (```json ... ```) from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence with optional language tag
        text = re.sub(r"^```(?:\w+)?\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _normalize_time_expr(expr: str) -> str:
    """Normalize bare hours like '\u0432 10' to '\u0432 10:00' for better dateparser handling."""
    # Handle Russian patterns: "\u0437\u0430\u0432\u0442\u0440\u0430 \u0432 10", "\u0432 10", "\u0437\u0430\u0432\u0442\u0440\u0430 \u0432 10:00"
    # Only add :00 to bare digits that look like hour references
    expr = re.sub(r"(\u0432\s+)(\d{1,2})\s*$", r"\1\2:00", expr, flags=re.IGNORECASE)
    return expr


def _parse_time(expr: str, tz_name: str) -> Optional[datetime]:
    """Parse a natural-language time expression using dateparser."""
    expr = _strip_preposition(expr.strip())
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)

    # Fast path: bare HH:MM \u2014 dateparser is unreliable for this case
    m = _HHMM_RE.match(expr)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        candidate = now.replace(hour=h, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    # Normalize bare hours before sending to dateparser
    expr = _normalize_time_expr(expr)

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
    # Strip imperative words so the LLM doesn't think it's being commanded
    clean_text = _preprocess_text(text)
    if clean_text != text:
        logger.info("extract_tasks: stripped imperative: %r -> %r", text, clean_text)
    try:
        raw_json = await client.complete(EXTRACT_SYSTEM_PROMPT, clean_text)
        logger.info("extract_tasks: LLM raw response: %r", raw_json[:500])
    except Exception as e:
        logger.error("extract_tasks: LLM error: %s", e)
        raise

    try:
        raw_json = _strip_json_fences(raw_json)
        items = json.loads(raw_json.strip())
        # LLM returned empty array — treat as no tasks, use fallback
        if not items:
            logger.info("extract_tasks: LLM returned empty array, using dateparser fallback")
            items = None
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning("extract_tasks: unparseable LLM response: %s", e)
        # Fallback 1: try to find a JSON array embedded in the text
        m = re.search(r"\[.*\]", raw_json, re.DOTALL)
        if m:
            try:
                items = json.loads(m.group(0))
                logger.info("extract_tasks: recovered JSON from embedded array")
            except (json.JSONDecodeError, IndexError):
                items = None
        else:
            items = None

    # Fallback 2: use cleaned text as a bare task, try to extract time ourselves
    if not items:
        title = clean_text.strip()
        time_expr = None
        parsed_time = None
        try:
            date_results = search_dates(clean_text, languages=["ru", "en"], settings={
                "TIMEZONE": tz_name,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
            })
            if date_results:
                time_str, parsed_time = date_results[0]
                title = clean_text.replace(time_str, "").strip()
                time_expr = time_str
                logger.info("extract_tasks: dateparser found time %r -> %s", time_str, parsed_time)
        except Exception as de:
            logger.debug("extract_tasks: search_dates failed: %s", de)

        # Fallback title: if title is empty or just noise, use "напоминание"
        title = title.strip()
        noise_words = {"поставим", "поставь", "поставить", "в", "задачу", "задание", "напоминание", "напомни", "создай", "добавь", "ну", "вот"}
        title_words = [w for w in re.split(r'\s+', title.lower()) if w and w not in noise_words]
        title = " ".join(title_words) if title_words else "напоминание"

        items = [{"title": title, "notes": None, "priority": "medium",
                 "time_expression": time_expr, "recurrence": None}]
        logger.info("extract_tasks: using raw text as fallback task: title=%r, time=%r", title, time_expr)

    tasks = []
    for item in items:
        try:
            time_expr = item.get("time_expression")
            # Fallback: LLM missed the time but raw text has HH:MM
            if not time_expr:
                m = _TIME_RE.search(text)  # search original text (may have time hints)
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
