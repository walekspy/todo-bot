from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from pathlib import Path


def build_scheduler(db_path: Path) -> AsyncIOScheduler:
    """Build APScheduler with SQLite persistent job store.

    Args:
        db_path: Path for the scheduler's SQLite database.
                 Pass a dedicated path (e.g. data/scheduler.db), not the app DB.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
    }
    scheduler = AsyncIOScheduler(jobstores=jobstores)
    return scheduler
