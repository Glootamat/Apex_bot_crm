"""Create a consistent on-demand database backup before a deployment."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from dotenv import load_dotenv

root = Path(os.getenv("APEX_RELEASE_ROOT", "/opt/apex-crm/current"))
load_dotenv(Path("/opt/apex-crm/shared/.env"))
sys.path.insert(0, str(root))
from backup import create_backup, verify_backup

target = create_backup(root / "workshop.sqlite3", Path("/opt/apex-crm/shared/backups"))
verify_backup(target)
print(target.name)
