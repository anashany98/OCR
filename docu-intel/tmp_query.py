import sqlite3, json, sys

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

print("=== TABLES ===")
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for r in c.fetchall():
    print(r[0])

print("\n=== RECENT SESSIONS (7 days) ===")
c.execute("""SELECT id, directory, title, time_created
             FROM session
             WHERE time_created > datetime('now', '-7 days')
             ORDER BY time_created DESC LIMIT 20""")
for r in c.fetchall():
    title = (r[2] or "(no title)")[:80]
    print(f"{r[0]} | {r[3]} | {title}")

print("\n=== ALL SESSIONS FOR THIS PROJECT (docu-intel) ===")
c.execute("""SELECT id, directory, title, time_created
             FROM session
             WHERE directory LIKE '%docu-intel%'
             ORDER BY time_created DESC LIMIT 30""")
for r in c.fetchall():
    title = (r[2] or "(no title)")[:80]
    print(f"{r[0]} | {r[3]} | {title}")

conn.close()
