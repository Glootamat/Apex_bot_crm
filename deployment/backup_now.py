"""Create a consistent on-demand SQLite backup before a deployment."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


root = Path("/opt/apex-crm")
target = root / "backups" / f"before_deploy_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(root / "workshop.sqlite3") as source, sqlite3.connect(target) as backup:
    source.backup(backup)
print(target.name)
