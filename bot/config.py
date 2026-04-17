from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv
from typing import Optional


@dataclass(frozen=True)
class Config:
    bot_token: str
    llm_provider: str   # "groq" | "anthropic" | "ollama"
    llm_api_key: str
    llm_model: str      # empty string = use provider default
    database_path: Path
    gdrive_service_account_json: Path
    gdrive_backup_folder_id: Optional[str]
    snooze_evening_hour: int
    snooze_morning_hour: int
    escalation_snooze_count: int

    def __post_init__(self) -> None:
        for name, val in [
            ("snooze_evening_hour", self.snooze_evening_hour),
            ("snooze_morning_hour", self.snooze_morning_hour),
        ]:
            if not 0 <= val <= 23:
                raise ValueError(f"{name} must be 0-23, got {val}")
        if self.snooze_morning_hour >= self.snooze_evening_hour:
            raise ValueError("snooze_morning_hour must be less than snooze_evening_hour")


def load_config() -> Config:
    load_dotenv()
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        llm_provider=os.getenv("LLM_PROVIDER", "groq"),
        llm_api_key=os.environ["LLM_API_KEY"],
        llm_model=os.getenv("LLM_MODEL", ""),
        database_path=Path(os.getenv("DATABASE_PATH", "data/bot.db")),
        gdrive_service_account_json=Path(
            os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json")
        ),
        gdrive_backup_folder_id=os.getenv("GDRIVE_BACKUP_FOLDER_ID") or None,
        snooze_evening_hour=int(os.getenv("SNOOZE_EVENING_HOUR", "19")),
        snooze_morning_hour=int(os.getenv("SNOOZE_MORNING_HOUR", "9")),
        escalation_snooze_count=int(os.getenv("ESCALATION_SNOOZE_COUNT", "3")),
    )
