import sqlite3, json
from datetime import datetime, timezone

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# Get user text parts from the "Solicitud" session
c.execute("""SELECT p.data
             FROM part p
             WHERE p.session_id = 'ses_0a5ed0703ffe8xAmd67rgi03Es'
             AND json_extract(p.data, '$.type') = 'text'
             ORDER BY p.time_created""")
rows = c.fetchall()
print("=== ses_0a5ed0703ffe8xAmd67rgi03Es (Solicitud de usuario y contraseña) ===")
for r in rows:
    d = json.loads(r[0])
    text = d.get('text', '')
    if text and len(text) > 5:
        print(f"  USER: {text[:200]}")

# Also check the "Auto Dream" current session
print("\n=== ses_0a5ed06ceffe316XEI9GE60P6U (Auto Dream - current) ===")
c.execute("""SELECT p.data
             FROM part p
             WHERE p.session_id = 'ses_0a5ed06ceffe316XEI9GE60P6U'
             AND json_extract(p.data, '$.type') = 'text'
             ORDER BY p.time_created""")
rows = c.fetchall()
for r in rows:
    d = json.loads(r[0])
    text = d.get('text', '')
    if text and len(text) > 5:
        print(f"  PART: {text[:200]}")

# Check what the user said in the biggest sessions (MIMO25 and BRIEF_MIMO_CHAT)
print("\n=== User messages in ses_0b5045af1ffeg9qbMzBcbBuBiL (MIMO25, 633 msgs) ===")
c.execute("""SELECT p.data
             FROM part p
             WHERE p.session_id = 'ses_0b5045af1ffeg9qbMzBcbBuBiL'
             AND json_extract(p.data, '$.type') = 'text'
             ORDER BY p.time_created
             LIMIT 30""")
rows = c.fetchall()
for i, r in enumerate(rows):
    d = json.loads(r[0])
    text = d.get('text', '')
    if text and len(text) > 3:
        print(f"  [{i}] {text[:200]}")

print("\n=== User messages in ses_0b144816cffeX80GNJl7biQcZ9 (MIMO 2.5 test, 365 msgs) ===")
c.execute("""SELECT p.data
             FROM part p
             WHERE p.session_id = 'ses_0b144816cffeX80GNJl7biQcZ9'
             AND json_extract(p.data, '$.type') = 'text'
             ORDER BY p.time_created
             LIMIT 30""")
rows = c.fetchall()
for i, r in enumerate(rows):
    d = json.loads(r[0])
    text = d.get('text', '')
    if text and len(text) > 3:
        print(f"  [{i}] {text[:200]}")

conn.close()
