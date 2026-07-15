import sqlite3, json, sys
from datetime import datetime, timezone

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

print("=== RECENT SESSIONS (all, last 50 by timestamp) ===")
c.execute("""SELECT id, directory, title, time_created
             FROM session
             ORDER BY time_created DESC LIMIT 50""")
for r in c.fetchall():
    ts = r[3]
    if ts and ts > 1000000000000:
        dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
    elif ts:
        dt = str(ts)
    else:
        dt = "N/A"
    title = (r[2] or "(no title)")[:80]
    print(f"{r[0]} | {dt} | {title}")

print("\n=== ALL SESSIONS FOR THIS PROJECT (docu-intel) ===")
c.execute("""SELECT id, directory, title, time_created
             FROM session
             WHERE directory LIKE '%docu-intel%'
             ORDER BY time_created DESC""")
for r in c.fetchall():
    ts = r[3]
    if ts and ts > 1000000000000:
        dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
    else:
        dt = str(ts)
    title = (r[2] or "(no title)")[:80]
    print(f"{r[0]} | {dt} | {title}")

print("\n=== SCHEMA: session columns ===")
c.execute("PRAGMA table_info(session)")
for r in c.fetchall():
    print(f"  {r[1]} ({r[2]})")

conn.close()
