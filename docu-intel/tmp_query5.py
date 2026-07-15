import sqlite3, json
from datetime import datetime, timezone

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# Search for user messages with rule/decision keywords in recent sessions
# First get session IDs for this project in last 7 days
c.execute("""SELECT id, title, time_created FROM session
             WHERE project_id = 'a6d223d8-afd6-42a3-8dc9-4004d9d2bfb1'
             AND title NOT LIKE '%checkpoint-writer%'
             ORDER BY time_created DESC LIMIT 20""")
session_ids = [r[0] for r in c.fetchall()]
placeholders = ','.join(['?'] * len(session_ids))

# Search for user messages with important keywords
keywords = ["always", "never", "remember", "rule", "must", "no hagas", "siempre", "nunca", "recuerda", "decision", "decided", "por favor", "importante"]
for kw in keywords:
    c.execute(f"""SELECT m.session_id, substr(m.data, 1, 500) as data_preview
                 FROM message m
                 WHERE m.session_id IN ({placeholders})
                 AND m.agent_id IS NULL
                 AND m.data LIKE ?
                 ORDER BY m.time_created DESC
                 LIMIT 3""", session_ids + [f'%{kw}%'])
    rows = c.fetchall()
    if rows:
        print(f"\n--- Keyword: {kw} ---")
        for r in rows:
            try:
                d = json.loads(r[1])
                content = d.get('content', '')
                if isinstance(content, list):
                    content = ' '.join([c.get('text', '') for c in content if isinstance(c, dict)])
                idx = content.lower().find(kw.lower())
                if idx >= 0:
                    start = max(0, idx-100)
                    end = min(len(content), idx+150)
                    snippet = content[start:end].replace('\n', ' ').strip()
                    print(f"  [{r[0][:30]}] ...{snippet}...")
            except:
                pass

# Also search for explicit user directives about code style / architecture
print("\n=== USER DIRECTIVES ABOUT CODE/ARCHITECTURE ===")
patterns = ["%', 'no rompas", "%nunca rompas%", "%siempre usa%", "%copia literal%", "%commit por%", "%un solo%", "%en castellano%", "%dimelo en%", "%sin hash%"]
for pat in ["no rompas", "copia literal", "commit por", "en castellano", "dimelo en castellano", "sin hash"]:
    c.execute(f"""SELECT m.session_id, substr(m.data, 1, 500) as data_preview
                 FROM message m
                 WHERE m.session_id IN ({placeholders})
                 AND m.agent_id IS NULL
                 AND LOWER(m.data) LIKE ?
                 ORDER BY m.time_created DESC
                 LIMIT 2""", session_ids + [f'%{pat}%'])
    rows = c.fetchall()
    if rows:
        print(f"\n--- Pattern: {pat} ---")
        for r in rows:
            try:
                d = json.loads(r[1])
                content = d.get('content', '')
                if isinstance(content, list):
                    content = ' '.join([c.get('text', '') for c in content if isinstance(c, dict)])
                idx = content.lower().find(pat.lower())
                if idx >= 0:
                    start = max(0, idx-80)
                    end = min(len(content), idx+180)
                    snippet = content[start:end].replace('\n', ' ').strip()
                    print(f"  [{r[0][:30]}] ...{snippet}...")
            except:
                pass

conn.close()
