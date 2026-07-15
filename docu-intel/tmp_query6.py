import sqlite3, json
from datetime import datetime, timezone

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# Get session IDs
c.execute("""SELECT id, title, time_created FROM session
             WHERE project_id = 'a6d223d8-afd6-42a3-8dc9-4004d9d2bfb1'
             AND title NOT LIKE '%checkpoint-writer%'
             ORDER BY time_created DESC LIMIT 15""")
sessions = c.fetchall()
session_ids = [r[0] for r in sessions]
placeholders = ','.join(['?'] * len(session_ids))

# Get ALL user messages from these sessions (user role in JSON data)
c.execute(f"""SELECT m.session_id, m.data, m.time_created
             FROM message m
             WHERE m.session_id IN ({placeholders})
             AND m.agent_id IS NULL
             AND json_extract(m.data, '$.role') = 'user'
             ORDER BY m.time_created DESC""", session_ids)
rows = c.fetchall()
print(f"Total user messages: {len(rows)}")

# Search for key patterns in user text
import re
patterns = [
    (r'siempre|always|nunca|never|recuerda|remember', 'RULE/REMEMBER'),
    (r'no rompas|no toques|no modifiques|no cambies', 'DO NOT TOUCH'),
    (r'copia literal|copy exactly|sin mejoras|no improvements', 'COPY EXACTLY'),
    (r'en castellano|dimelo en|responde en|habla en|responder en', 'LANGUAGE'),
    (r'commit por|un commit|cada tarea|one commit', 'COMMIT STYLE'),
    (r'dcision|decided|decidimos|hemos decidido|tradeoff', 'DECISION'),
    (r'por favor|please|importante|critical|urgente', 'REQUEST'),
    (r'hash|fallback|sin fallback', 'EMBEDDING RULE'),
]

for regex, label in patterns:
    found = []
    for r in rows:
        try:
            d = json.loads(r[0])
        except:
            d = {}
        try:
            data = json.loads(r[1])
        except:
            continue
        content = data.get('content', '')
        if isinstance(content, list):
            texts = [c.get('text', '') for c in content if isinstance(c, dict)]
            content = ' '.join(texts)
        if not content:
            continue

        matches = list(re.finditer(regex, content, re.IGNORECASE))
        for m in matches:
            start = max(0, m.start() - 100)
            end = min(len(content), m.end() + 150)
            snippet = content[start:end].replace('\n', ' ').strip()
            sid = r[2][:30] if r[2] else "?"
            found.append(f"  [{sid}] ...{snippet}...")

    if found:
        print(f"\n=== {label} ({len(found)} matches) ===")
        for f in found[:5]:
            print(f)

conn.close()
