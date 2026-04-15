from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Task:
    title: str
    owner_id: int
    chat_id: int
    remind_at: datetime
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notes: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.MEDIUM
    source: str = "manual"
    source_ref: Optional[str] = None
    due_at: Optional[datetime] = None
    recurrence: Optional[str] = None
    snoozed_until: Optional[datetime] = None
    snooze_count: int = 0
    assignee_id: Optional[int] = None
    is_family: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WatchedSource:
    owner_id: int
    chat_id: int
    url: str
    source_type: str  # "google_doc" | "md_file"
    reminder_lead_days: int = 3
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    last_checked: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class User:
    telegram_id: int
    username: Optional[str] = None
    family_chat_id: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
