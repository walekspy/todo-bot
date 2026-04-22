"""Two-way sync between bot tasks and Google Tasks."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from bot.db.models import Task, TaskStatus, Priority
from bot.db.repository import TaskRepo

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/tasks"]


@dataclass
class SyncStats:
    pulled_new: int = 0
    pulled_updated: int = 0
    pushed_new: int = 0
    pushed_updated: int = 0
    errors: int = 0
    no_time_tasks: list = None  # list of (task_id, title) without explicit time

    def __post_init__(self):
        if self.no_time_tasks is None:
            self.no_time_tasks = []

    def __str__(self) -> str:
        lines = []
        if self.pulled_new:
            lines.append(f"⬇️ Создано из Google: {self.pulled_new}")
        if self.pulled_updated:
            lines.append(f"🔄 Обновлено из Google: {self.pulled_updated}")
        if self.pushed_new:
            lines.append(f"⬆️ Отправлено в Google: {self.pushed_new}")
        if self.pushed_updated:
            lines.append(f"✏️ Обновлено в Google: {self.pushed_updated}")
        if self.errors:
            lines.append(f"⚠️ Ошибок: {self.errors}")
        return "\n".join(lines) if lines else "Изменений нет."


def _load_service(token_path: Path):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return build("tasks", "v1", credentials=creds)


def _extract_time_from_notes(notes: Optional[str]) -> Optional[tuple[int, int]]:
    """Parse '⏰ HH:MM' written by _build_notes; returns (hour, minute) or None."""
    if not notes:
        return None
    first_line = notes.splitlines()[0].strip()
    if first_line.startswith("⏰ "):
        time_part = first_line[2:].strip()
        try:
            h, m = time_part.split(":")
            return int(h), int(m)
        except ValueError:
            pass
    return None


def _due_to_remind_at(gt_due: Optional[datetime], tz_name: str,
                      notes: Optional[str] = None) -> datetime:
    """Convert Google due date to remind_at.

    If notes contain '⏰ HH:MM' (written by this bot), use that time.
    Otherwise default to 9:00 AM local time on the due date.
    """
    tz = ZoneInfo(tz_name)
    hm = _extract_time_from_notes(notes)
    hour, minute = hm if hm else (9, 0)

    if gt_due:
        local_date = gt_due.astimezone(tz).date()
        return datetime(local_date.year, local_date.month, local_date.day,
                        hour, minute, 0, tzinfo=tz)
    # No due date — tomorrow at the extracted (or default) time
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day,
                    hour, minute, 0, tzinfo=tz)


def _parse_google_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _google_status_to_bot(s: str) -> TaskStatus:
    return TaskStatus.DONE if s == "completed" else TaskStatus.PENDING


def _bot_status_to_google(s: TaskStatus) -> str:
    return "completed" if s == TaskStatus.DONE else "needsAction"


def _fetch_all_tasklists(service) -> list[dict]:
    result = service.tasklists().list(maxResults=100).execute()
    return result.get("items", [])


def _fetch_tasks_in_list(service, tl_id: str) -> list[dict]:
    result = service.tasks().list(
        tasklist=tl_id,
        showCompleted=True,
        showHidden=True,
        maxResults=100,
    ).execute()
    return result.get("items", [])


def _build_notes(task: Task, tz_name: str) -> str:
    """Build Google task notes, prepending reminder time since API is date-only."""
    parts = []
    if task.remind_at:
        tz = ZoneInfo(tz_name)
        local = task.remind_at.astimezone(tz)
        parts.append(f"⏰ {local.strftime('%H:%M')}")
    if task.notes:
        parts.append(task.notes)
    return "\n".join(parts)


def _create_google_task(service, tl_id: str, task: Task, tz_name: str = "UTC") -> dict:
    body = {
        "title": task.title,
        "notes": _build_notes(task, tz_name),
        "status": _bot_status_to_google(task.status),
    }
    if task.remind_at:
        body["due"] = task.remind_at.strftime("%Y-%m-%dT00:00:00.000Z")
    return service.tasks().insert(tasklist=tl_id, body=body).execute()


def _update_google_task(service, tl_id: str, gt_id: str, task: Task, tz_name: str = "UTC") -> dict:
    body = {
        "title": task.title,
        "notes": _build_notes(task, tz_name),
        "status": _bot_status_to_google(task.status),
    }
    if task.remind_at:
        body["due"] = task.remind_at.strftime("%Y-%m-%dT00:00:00.000Z")
    return service.tasks().patch(
        tasklist=tl_id, task=gt_id, body=body
    ).execute()


async def sync_google_tasks(
    task_repo: TaskRepo,
    token_path: Path,
    default_owner_id: int,
    default_chat_id: int,
    tz_name: str = "UTC",
) -> SyncStats:
    stats = SyncStats()
    now = datetime.now(timezone.utc)

    service = await asyncio.to_thread(_load_service, token_path)

    # ── Pull: Google → Bot ──────────────────────────────────────────────
    tasklists = await asyncio.to_thread(_fetch_all_tasklists, service)
    first_tl_id = tasklists[0]["id"] if tasklists else None

    for tl in tasklists:
        tl_id = tl["id"]
        tl_title = tl.get("title", "Google Tasks")

        google_tasks = await asyncio.to_thread(_fetch_tasks_in_list, service, tl_id)

        for gt in google_tasks:
            if not gt.get("title"):
                continue
            gt_id = gt["id"]
            gt_updated = _parse_google_dt(gt.get("updated"))
            gt_status = _google_status_to_bot(gt.get("status", "needsAction"))
            gt_due = _parse_google_dt(gt.get("due"))
            gt_notes = gt.get("notes") or None

            existing = await task_repo.get_by_google_id(gt_id)

            if existing is None:
                # New task from Google — create in bot
                has_time = _extract_time_from_notes(gt_notes) is not None
                task = Task(
                    title=gt["title"],
                    notes=gt_notes,
                    status=gt_status,
                    source="google_tasks",
                    source_ref=tl_title,
                    due_at=gt_due,
                    remind_at=_due_to_remind_at(gt_due, tz_name, gt_notes),
                    owner_id=default_owner_id,
                    chat_id=default_chat_id,
                    google_task_id=gt_id,
                    google_tasklist_id=tl_id,
                    google_updated_at=gt_updated,
                )
                try:
                    await task_repo.save(task)
                    stats.pulled_new += 1
                    if not has_time:
                        stats.no_time_tasks.append((task.id, gt["title"]))
                except Exception as e:
                    logger.error("Failed to save task from Google: %s", e)
                    stats.errors += 1
            else:
                # Existing task — update if Google is newer
                g_newer = gt_updated and (
                    existing.google_updated_at is None
                    or gt_updated > existing.google_updated_at
                )
                if g_newer:
                    try:
                        await task_repo.update_from_google(
                            task_id=existing.id,
                            title=gt["title"],
                            notes=gt_notes,
                            status=gt_status,
                            due_at=gt_due,
                            remind_at=_due_to_remind_at(gt_due, tz_name, gt_notes),
                            google_updated_at=gt_updated,
                        )
                        stats.pulled_updated += 1
                    except Exception as e:
                        logger.error("Failed to update task from Google: %s", e)
                        stats.errors += 1

    # ── Push: Bot → Google ──────────────────────────────────────────────
    bot_tasks = await task_repo.list_all_active()

    for task in bot_tasks:
        if task.google_task_id is None:
            # New bot task — push to Google
            if not first_tl_id:
                continue
            try:
                result = await asyncio.to_thread(
                    _create_google_task, service, first_tl_id, task, tz_name
                )
                g_updated = _parse_google_dt(result.get("updated"))
                await task_repo.set_google_task_id(
                    task.id, result["id"], first_tl_id, g_updated
                )
                stats.pushed_new += 1
            except Exception as e:
                logger.error("Failed to push task to Google: %s", e)
                stats.errors += 1
        else:
            # Existing — push if bot is newer than last google sync
            bot_newer = (
                task.updated_at
                and task.google_updated_at
                and task.updated_at > task.google_updated_at
            )
            if bot_newer:
                try:
                    result = await asyncio.to_thread(
                        _update_google_task, service,
                        task.google_tasklist_id, task.google_task_id, task, tz_name
                    )
                    g_updated = _parse_google_dt(result.get("updated"))
                    await task_repo.set_google_task_id(
                        task.id, task.google_task_id,
                        task.google_tasklist_id, g_updated
                    )
                    stats.pushed_updated += 1
                except Exception as e:
                    logger.error("Failed to update Google task: %s", e)
                    stats.errors += 1

    return stats
