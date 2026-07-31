"""Local SQLite backups for the workshop CRM."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def create_backup(database_path: Path, backup_dir: Path, retention_days: int = 30) -> Path:
    """Create a consistent SQLite snapshot and remove expired snapshots."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination = backup_dir / f"workshop_{timestamp}.sqlite3"
    source = sqlite3.connect(database_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    threshold = datetime.now() - timedelta(days=retention_days)
    for file in backup_dir.glob("workshop_*.sqlite3"):
        if file != destination and datetime.fromtimestamp(file.stat().st_mtime) < threshold:
            file.unlink()
    return destination


def verify_backup(database_path: Path) -> None:
    """Raise when a newly-created SQLite backup cannot be read cleanly."""
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result}")
    finally:
        connection.close()
