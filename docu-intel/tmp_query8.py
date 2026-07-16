import sqlite3, json

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# Get the first user message from the MIMO25 session - check full structure
c.execute("""SELECT m.data
             FROM message m
             WHERE m.session_id = 'ses_0b5045af1ffeg9qbMzBcbBuBiL'
             AND json_extract(m.data, '$.role') = 'user'
             ORDER BY m.time_created
             LIMIT 1""")
row = c.fetchone()
if row:
    d = json.loads(row[0])
    print("User message keys:", list(d.keys()))
    print("Full data (truncated):", json.dumps(d, indent=2, ensure_ascii=False)[:2000])

# Get the part table schema
print("\n=== PART TABLE SCHEMA ===")
c.execute("PRAGMA table_info(part)")
for r in c.fetchall():
    print(f"  {r[1]} ({r[2]})")

# Check part data for user messages
c.execute("""SELECT p.session_id, substr(p.data, 1, 400) as preview
             FROM part p
             WHERE p.session_id = 'ses_0b5045af1ffeg9qbMzBcbBuBiL'
             ORDER BY p.time_created
             LIMIT 5""")
rows = c.fetchall()
print("\n=== Sample parts ===")
for r in rows:
    print(f"  {r[1]}")
    print()

conn.close()
