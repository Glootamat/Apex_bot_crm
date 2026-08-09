"""Consistent SQLite or PostgreSQL backups for the workshop CRM."""

from __future__ import annotations

import sqlite3
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, unquote


def create_backup(database_path: Path, backup_dir: Path, retention_days: int = 30) -> Path:
    """Create a consistent database snapshot and remove expired snapshots."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith(("postgresql://", "postgres://")):
        destination = backup_dir / f"workshop_{timestamp}.dump"
        parsed = urlsplit(database_url)
        environment = os.environ.copy()
        environment["PGPASSWORD"] = unquote(parsed.password or "")
        subprocess.run([
            os.getenv("PG_DUMP_BIN", "pg_dump"), "--format=custom", "--no-owner",
            "--host", parsed.hostname or "127.0.0.1", "--port", str(parsed.port or 5432),
            "--username", unquote(parsed.username or ""), "--file", str(destination),
            unquote(parsed.path.lstrip("/")),
        ], check=True, env=environment, capture_output=True)
        _remove_expired(backup_dir, destination, retention_days)
        return destination
    destination = backup_dir / f"workshop_{timestamp}.sqlite3"
    source = sqlite3.connect(database_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    _remove_expired(backup_dir, destination, retention_days)
    return destination


def verify_backup(database_path: Path) -> None:
    """Raise when a newly-created backup cannot be read cleanly."""
    if database_path.suffix == ".dump":
        result = subprocess.run(
            [os.getenv("PG_RESTORE_BIN", "pg_restore"), "--list", str(database_path)],
            check=True, capture_output=True,
        )
        if not result.stdout:
            raise RuntimeError("PostgreSQL backup is empty")
        return
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result}")
    finally:
        connection.close()


def _remove_expired(backup_dir: Path, destination: Path, retention_days: int) -> None:
    threshold = datetime.now() - timedelta(days=retention_days)
    for pattern in ("workshop_*.sqlite3", "workshop_*.dump"):
        for file in backup_dir.glob(pattern):
            if file != destination and datetime.fromtimestamp(file.stat().st_mtime) < threshold:
                file.unlink()
