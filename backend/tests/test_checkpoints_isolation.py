import pytest
from pathlib import Path
from app.config import settings

def test_checkpoints_storage_configuration():
    assert settings.checkpoints_sqlite_path == "data/checkpoints.db"
    file_path = settings.checkpoints_sqlite_file
    assert file_path.name == "checkpoints.db"
    assert file_path != settings.sqlite_file
