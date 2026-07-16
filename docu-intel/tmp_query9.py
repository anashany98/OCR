import sqlite3, json, re
from datetime import datetime, timezone

DB = r"C:\Users\Usuario\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# Get all session IDs for this project (non-checkpoint-writer)
c.execute("""SELECT id FROM session
             WHERE project_id = 'a6d223d8-afd6-42a3-8dc9-4004d9d2bfb1'
             AND title NOT LIKE '%checkpoint-writer%'
             ORDER BY time_created DESC LIMIT 20""")
session_ids = [r[0] for r in c.fetchall()]
placeholders = ','.join(['?'] * len(session_ids))

# Get all user text parts from these sessions
c.execute(f"""SELECT p.session_id, p.data, p.time_created
             FROM part p
             WHERE p.session_id IN ({placeholders})
             AND json_extract(p.data, '$.type') = 'text'
             ORDER BY p.time_created DESC""", session_ids)
rows = c.fetchall()
print(f"Total user text parts: {len(rows)}")

# Search for key patterns
patterns = [
    (r'siempre|always|nunca|never|recuerda|remember|rule|regla', 'RULE/REMEMBER'),
    (r'no rompas|no toques|no modifiques|no cambies|sin tocar', 'DO NOT TOUCH'),
    (r'copia literal|copy exactly|sin mejoras|no improvements|copy code', 'COPY EXACTLY'),
    (r'en castellano|dimelo en|responde en|habla en|responder en|castellano', 'LANGUAGE'),
    (r'commit por|un commit|cada tarea|one commit per', 'COMMIT STYLE'),
    (r'decision|decided|decidimos|hemos decidido|tradeoff|trade-off|razon', 'DECISION'),
    (r'hash|fallback|sin fallback|sin hash', 'EMBEDDING'),
    (r'phase|fase|FASE|milestone', 'PHASE/FASE'),
]

for regex, label in patterns:
    found = []
    for r in rows:
        try:
            d = json.loads(r[1])
            text = d.get('text', '')
        except:
            continue
        if not text:
            continue

        matches = list(re.finditer(regex, text, re.IGNORECASE))
        for m in matches:
            start = max(0, m.start() - 120)
            end = min(len(text), m.end() + 200)
            snippet = text[start:end].replace('\n', ' ').strip()
            # Get session date
            try:
                dt = datetime.fromtimestamp(r[2]/1000, tz=timezone.utc).strftime('%Y-%m-%d')
            except:
                dt = "?"
            found.append(f"  [{r[0][:25]} | {dt}] ...{snippet}...")

    if found:
        print(f"\n=== {label} ({len(found)} matches) ===")
        for f in found[:8]:
            print(f)

conn.close()
