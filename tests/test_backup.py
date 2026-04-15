import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path


@pytest.mark.asyncio
async def test_upload_backup_calls_drive_api(tmp_path):
    db_file = tmp_path / "bot.db"
    db_file.write_bytes(b"SQLite data")

    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_service.files.return_value = mock_files
    mock_files.list.return_value.execute.return_value = {"files": []}
    mock_files.create.return_value.execute.return_value = {"id": "new_file_id"}

    with patch("bot.backup.gdrive._build_drive_service", return_value=mock_service):
        from bot.backup.gdrive import upload_backup
        await upload_backup(db_file, folder_id="test_folder", service_account_json=Path("creds.json"))

    mock_files.create.assert_called_once()


@pytest.mark.asyncio
async def test_upload_backup_skips_missing_db(tmp_path):
    missing = tmp_path / "missing.db"
    with patch("bot.backup.gdrive._build_drive_service") as mock_build:
        from bot.backup.gdrive import upload_backup
        await upload_backup(missing, folder_id="test_folder", service_account_json=Path("creds.json"))
    mock_build.assert_not_called()


@pytest.mark.asyncio
async def test_upload_backup_prunes_old_backups(tmp_path):
    db_file = tmp_path / "bot.db"
    db_file.write_bytes(b"data")

    # Return 32 existing backups (more than MAX_BACKUPS=30)
    old_files = [{"id": f"file_{i}", "name": f"bot_backup_{i}.db"} for i in range(32)]
    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_service.files.return_value = mock_files
    mock_files.list.return_value.execute.return_value = {"files": old_files}
    mock_files.create.return_value.execute.return_value = {"id": "new_id"}

    with patch("bot.backup.gdrive._build_drive_service", return_value=mock_service):
        from bot.backup.gdrive import upload_backup
        await upload_backup(db_file, folder_id="test_folder", service_account_json=Path("creds.json"))

    # Should delete 2 oldest (indices 30, 31)
    assert mock_files.delete.call_count == 2
