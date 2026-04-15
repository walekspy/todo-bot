import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
MAX_BACKUPS = 30
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _build_drive_service(service_account_json: Path) -> Any:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_file(str(service_account_json), scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


async def upload_backup(db_path: Path, folder_id: str, service_account_json: Path) -> None:
    """Upload SQLite backup to Google Drive, keeping the newest MAX_BACKUPS files."""
    if not db_path.exists():
        logger.warning("Backup: database file not found at %s — skipping", db_path)
        return

    def _upload() -> None:
        from googleapiclient.http import MediaFileUpload
        service = _build_drive_service(service_account_json)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"bot_backup_{timestamp}.db"

        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(str(db_path), mimetype="application/x-sqlite3")
        service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        logger.info("Backup: uploaded %s", filename)

        # Prune — keep only the newest MAX_BACKUPS
        result = service.files().list(
            q=f"'{folder_id}' in parents and name contains 'bot_backup_'",
            orderBy="createdTime desc",
            fields="files(id, name)",
        ).execute()
        old_files = result.get("files", [])[MAX_BACKUPS:]
        for old in old_files:
            service.files().delete(fileId=old["id"]).execute()
            logger.info("Backup: pruned %s", old["name"])

    await asyncio.to_thread(_upload)
