# ✅ IN DATA PIPE_LINE 10-06-26  (run manually once before starting the backfill loop)
"""
Step 1 — Restore SQL Server .bak backup file using sqlcmd.
Run this script via Task Scheduler before 02_extract_load.py.

Requirements:
  - SQL Server installed with sqlcmd in PATH
  - ODBC Driver 17 for SQL Server installed
  - Update BACKUP_FILE path to match your actual .bak file location
"""

import subprocess
import sys
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Configuration ──────────────────────────────────────────────────────────────
SERVER      = os.environ["MSSQL_SERVER"]
DATABASE    = os.environ["MSSQL_DATABASE"]
USER        = os.environ["MSSQL_USER"]
PASSWORD    = os.environ["MSSQL_PASSWORD"]
BACKUP_FILE = os.environ["BACKUP_FILE"]
# ───────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def restore_database():
    log.info(f"Starting restore of '{DATABASE}' from: {BACKUP_FILE}")

    if not Path(BACKUP_FILE).exists():
        log.error(f"Backup file not found: {BACKUP_FILE}")
        sys.exit(1)

    sql = (
        f"RESTORE DATABASE [{DATABASE}] "
        f"FROM DISK='{BACKUP_FILE}' "
        f"WITH REPLACE, RECOVERY;"
    )

    result = subprocess.run(
        ["sqlcmd", "-S", SERVER, "-U", USER, "-P", PASSWORD, "-Q", sql],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        log.error(f"sqlcmd failed:\n{result.stderr}")
        sys.exit(1)

    log.info(f"Restore completed successfully.\n{result.stdout}")


if __name__ == "__main__":
    restore_database()
