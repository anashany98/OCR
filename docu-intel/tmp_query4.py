import sqlite3, json
from datetime import datetime, timezone

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# Check message schema
print("=== MESSAGE TABLE SCHEMA ===")
c.execute("PRAGMA table_info(message)")
for r in c.fetchall():
    print(f"  {r[1]} ({r[2]})")

conn.close()
