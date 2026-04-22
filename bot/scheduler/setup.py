from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.memory import MemoryJobStore
from pathlib import Path


def build_scheduler(db_path: Path) -> AsyncIOScheduler:
    """Build APScheduler with two job stores:

    - "default" (MemoryJobStore): task reminders, doc checks — contain
      non-picklable objects (bot, repos). Recreated from DB on startup.
    - "persistent" (SQLAlchemyJobStore): backup_job only — uses string
      reference and plain kwargs, survives restarts without reconciliation.

    Args:
        db_path: Path for the scheduler's SQLite database.
                 Pass a dedicated path (e.g. data/scheduler.db), not the app DB.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    jobstores = {
        "default": MemoryJobStore(),
        "persistent": SQLAlchemyJobStore(url=f"sqlite:///{db_path}"),
    }
    scheduler = AsyncIOScheduler(jobstores=jobstores)
    return scheduler
