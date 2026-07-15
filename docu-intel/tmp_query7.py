import sqlite3, json

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# Check message data format
c.execute("""SELECT m.session_id, m.agent_id, substr(m.data, 1, 300) as preview
             FROM message m
             WHERE m.session_id = 'ses_0b5045af1ffeg9qbMzBcbBuBiL'
             ORDER BY m.time_created
             LIMIT 10""")
rows = c.fetchall()
print("=== Sample messages from MIMO25 session ===")
for r in rows:
    print(f"  session={r[0][:25]} agent={r[1]}")
    print(f"  data preview: {r[2]}")
    print()

conn.close()
