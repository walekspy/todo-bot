from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from bot.db.models import Priority


@dataclass
class RawTask:
    title: str
    priority: Priority = Priority.MEDIUM
    notes: Optional[str] = None
    due_at: Optional[datetime] = None
    remind_at: Optional[datetime] = None
    recurrence: Optional[str] = None
    source: str = "manual"
    source_ref: Optional[str] = None


class SourceAdapter(ABC):
    @abstractmethod
    async def extract(self, input_data: str) -> list[RawTask]:
        """Parse input_data and return candidate tasks for user confirmation."""
