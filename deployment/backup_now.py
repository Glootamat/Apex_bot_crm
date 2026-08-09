"""Create a consistent on-demand database backup before a deployment."""

from __future__ import annotations

from pathlib import Path
import sys

root = Path("/opt/apex-crm")
sys.path.insert(0, str(root))
from backup import create_backup, verify_backup

target = create_backup(root / "workshop.sqlite3", root / "backups")
verify_backup(target)
print(target.name)
