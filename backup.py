import sqlite3
from datetime import datetime
from pathlib import Path

Path("backups").mkdir(exist_ok=True)
name = "backups/smartshop_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".db"

source = sqlite3.connect("smartshop.db")
target = sqlite3.connect(name)
source.backup(target)
target.close()
source.close()

print("Backup saved:", name)