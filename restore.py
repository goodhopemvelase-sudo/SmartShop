import sqlite3
import sys
from datetime import datetime
from pathlib import Path

if len(sys.argv) != 2:
    print("Usage: python restore.py backups\\FILE.db")
    sys.exit(1)

backup_file = Path(sys.argv[1])
if not backup_file.exists():
    print("File not found:", backup_file)
    sys.exit(1)

check = sqlite3.connect(backup_file)
result = check.execute("PRAGMA integrity_check").fetchone()[0]
check.close()
if result != "ok":
    print("This backup is damaged. Restore cancelled.")
    sys.exit(1)

Path("backups").mkdir(exist_ok=True)
if Path("smartshop.db").exists():
    safety = "backups/before_restore_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".db"
    current = sqlite3.connect("smartshop.db")
    copy = sqlite3.connect(safety)
    current.backup(copy)
    copy.close()
    current.close()
    print("Current data saved first as:", safety)

source = sqlite3.connect(backup_file)
target = sqlite3.connect("smartshop.db")
source.backup(target)
target.close()
source.close()
print("Restore complete.")