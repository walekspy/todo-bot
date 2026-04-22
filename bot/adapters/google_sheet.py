"""Read Google Sheets via Sheets API (service account)."""
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _spreadsheet_id_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if "google.com" not in parsed.netloc:
        return None
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", parsed.path)
    return match.group(1) if match else None


def is_sheets_url(url: str) -> bool:
    return _spreadsheet_id_from_url(url) is not None


def _build_service(sa_json_path: Path):
    creds = Credentials.from_service_account_file(str(sa_json_path), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def fetch_sheet_names(sa_json_path: Path, url: str) -> list[str]:
    sid = _spreadsheet_id_from_url(url)
    if not sid:
        raise ValueError(f"Cannot extract spreadsheet ID from URL: {url}")
    service = _build_service(sa_json_path)
    meta = service.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties.title").execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def fetch_sheet_content(sa_json_path: Path, url: str, sheet_name: str) -> str:
    sid = _spreadsheet_id_from_url(url)
    if not sid:
        raise ValueError(f"Cannot extract spreadsheet ID from URL: {url}")
    service = _build_service(sa_json_path)
    result = service.spreadsheets().values().get(
        spreadsheetId=sid, range=sheet_name
    ).execute()
    rows = result.get("values", [])
    if not rows:
        return ""
    lines = []
    for row in rows:
        lines.append("\t".join(str(cell) for cell in row))
    return "\n".join(lines)
