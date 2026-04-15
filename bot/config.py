from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    anthropic_api_key: str
    database_path: Path
    gdrive_service_account_json: Path
    gdrive_backup_folder_id: str
    snooze_evening_hour: int
    snooze_morning_hour: int
    escalation_snooze_count: int


def load_config() -> Config:
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        database_path=Path(os.getenv("DATABASE_PATH", "data/bot.db")),
        gdrive_service_account_json=Path(
            os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json")
        ),
        gdrive_backup_folder_id=os.getenv("GDRIVE_BACKUP_FOLDER_ID", ""),
        snooze_evening_hour=int(os.getenv("SNOOZE_EVENING_HOUR", "19")),
        snooze_morning_hour=int(os.getenv("SNOOZE_MORNING_HOUR", "9")),
        escalation_snooze_count=int(os.getenv("ESCALATION_SNOOZE_COUNT", "3")),
    )
