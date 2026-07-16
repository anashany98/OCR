import sqlite3, json
from datetime import datetime, timezone

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

print("=== PROJECT TABLE SCHEMA ===")
c.execute("PRAGMA table_info(project)")
for r in c.fetchall():
    print(f"  {r[1]} ({r[2]})")

c.execute("SELECT * FROM project")
for r in c.fetchall():
    print(f"  PROJECT: {r}")

# Get current session's project_id
print("\n=== CURRENT SESSION ===")
c.execute("SELECT id, project_id, directory, title, time_created FROM session WHERE id = 'ses_0a5ed06ceffe316XEI9GE60P6U'")
row = c.fetchone()
if row:
    current_pid = row[1]
    print(f"  id={row[0]} | project={current_pid} | dir={row[2]} | title={row[3]}")
else:
    print("  NOT FOUND")
    current_pid = None

if current_pid:
    print(f"\n=== ALL SESSIONS FOR PROJECT {current_pid} (non-checkpoint-writer) ===")
    c.execute("""SELECT id, directory, title, time_created
                 FROM session
                 WHERE project_id = ?
                 AND title NOT LIKE '%checkpoint-writer%'
                 ORDER BY time_created DESC LIMIT 50""", (current_pid,))
    for r in c.fetchall():
        ts = r[3]
        if ts and ts > 1000000000000:
            dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        else:
            dt = str(ts)
        title = (r[2] or "(no title)")[:80]
        print(f"  {r[0]} | {dt} | {title}")

    # Count messages per user session
    print(f"\n=== MESSAGE COUNTS PER SESSION ===")
    c.execute("""SELECT s.id, s.title, COUNT(m.id) as msg_count
                 FROM session s
                 JOIN message m ON m.session_id = s.id
                 WHERE s.project_id = ?
                 AND s.title NOT LIKE '%checkpoint-writer%'
                 GROUP BY s.id
                 ORDER BY s.time_created DESC LIMIT 20""", (current_pid,))
    for r in c.fetchall():
        title = (r[1] or "(no title)")[:60]
        print(f"  {r[0]} | {r[2]} msgs | {title}")

conn.close()
