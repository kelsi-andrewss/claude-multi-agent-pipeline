---
name: prefs
disable-model-invocation: true
description: >
  View, add, edit, remove, export, and import behavioral preferences stored
  in correction_groups. Use when the user says "/prefs", "/prefs list",
  "/prefs add", "/prefs edit", "/prefs remove", "/prefs export", or
  "/prefs import".
args:
  - name: args
    type: string
    description: >
      Subcommand and arguments. Subcommands: list (default), add "<text>",
      edit N "<text>", remove N, export [path], import <path>.
---

# Prefs Skill Invoked

User has requested: `/prefs {{args}}`

**DB path:** `"$HOME/.claude/.claude/epics.db"`

**SQL injection guard:** All SQL operations use python3 with parameterized queries (`cursor.execute` with `?` placeholders). Never use string interpolation for user input.

---

## Subcommand dispatch

Parse the first token of `{{args}}`:

- **`list`** or **empty/unrecognized** → go to **List**
- **`add`** → go to **Add**
- **`edit`** → go to **Edit**
- **`remove`** → go to **Remove**
- **`export`** → go to **Export**
- **`import`** → go to **Import**

---

## List

Display live preferences from the database:

```bash
python3 -c "
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1], timeout=5)
rows = conn.execute(
    'SELECT source, text FROM correction_groups '
    'WHERE (status IN (?,?) OR source=?) AND text != ? '
    'ORDER BY updated_at DESC',
    ('promoted', 'pending_promotion', 'manual', '')
).fetchall()
conn.close()
for i, (source, text) in enumerate(rows, 1):
    print(f'{i}. [{source}] {text}')
" "$HOME/.claude/.claude/epics.db"
```

> If the query returns empty output, say: "No preferences found. Use `/prefs add \"<text>\"` to add one."

After the list, show:

```
Commands: /prefs add "<text>" | /prefs edit N "<text>" | /prefs remove N
          /prefs export [path] | /prefs import <path>
```

> If the query errors with "no such column: source" or "no such column: text", say: "The prefs schema hasn't been migrated yet. Run `bash "$HOME/.claude/scripts/evolve-prefs-schema.sh"` first."

Stop.

---

## Add

Parse everything after `add` as the preference text. Strip outer quotes if present.

1. If text is empty, say: "Usage: `/prefs add \"<preference text>\"`" and stop.
2. Derive a theme: first 60 characters of text, lowercased.
3. Run:
   ```bash
   python3 -c "
   import sqlite3, sys, time
   conn = sqlite3.connect(sys.argv[1], timeout=5)
   now = int(time.time())
   conn.execute(
       'INSERT INTO correction_groups (theme, status, source, text, count, created_at, updated_at) '
       'VALUES (?, ?, ?, ?, NULL, ?, ?)',
       (sys.argv[2], 'promoted', 'manual', sys.argv[3], now, now)
   )
   conn.commit()
   conn.close()
   " "$HOME/.claude/.claude/epics.db" "<theme>" "<text>"
   ```
4. Shadow to OpenMemory:
   ```bash
   python3 "$HOME/.claude/.claude/hooks/lib/om_write.py" "behavioral-pref" "<text>" "global"
   ```
5. Confirm: "Added preference." then show the updated list by running the **List** query.

Stop.

---

## Edit

Parse `edit N "<new text>"` where N is a 1-based row number and the rest is the new text.

1. If N is not a positive integer or text is empty, say: "Usage: `/prefs edit N \"<new text>\"`" and stop.
2. Derive a theme from the new text.
3. Resolve row number N to the actual `id` and update in one script:
   ```bash
   python3 -c "
   import sqlite3, sys, time
   conn = sqlite3.connect(sys.argv[1], timeout=5)
   row = conn.execute(
       'SELECT id FROM correction_groups '
       'WHERE (status IN (?,?) OR source=?) AND text != ? '
       'ORDER BY updated_at DESC LIMIT 1 OFFSET ?',
       ('promoted', 'pending_promotion', 'manual', '', int(sys.argv[2]) - 1)
   ).fetchone()
   if not row:
       print('NOT_FOUND')
       sys.exit(0)
   now = int(time.time())
   conn.execute(
       'UPDATE correction_groups SET text=?, theme=?, updated_at=? WHERE id=?',
       (sys.argv[3], sys.argv[4], now, row[0])
   )
   conn.commit()
   conn.close()
   print(f'UPDATED:{row[0]}')
   " "$HOME/.claude/.claude/epics.db" "<N>" "<new-text>" "<theme>"
   ```
4. If output is `NOT_FOUND`, say: "Preference #N does not exist. Run `/prefs list` to see current preferences." and stop.
5. Confirm: "Updated preference #N." then show the updated list by running the **List** query.

Stop.

---

## Remove

Parse `remove N` where N is a 1-based row number.

1. If N is not a positive integer, say: "Usage: `/prefs remove N`" and stop.
2. Resolve row number N, read the text, and delete in one script:
   ```bash
   python3 -c "
   import sqlite3, sys
   conn = sqlite3.connect(sys.argv[1], timeout=5)
   row = conn.execute(
       'SELECT id, text FROM correction_groups '
       'WHERE (status IN (?,?) OR source=?) AND text != ? '
       'ORDER BY updated_at DESC LIMIT 1 OFFSET ?',
       ('promoted', 'pending_promotion', 'manual', '', int(sys.argv[2]) - 1)
   ).fetchone()
   if not row:
       print('NOT_FOUND')
       sys.exit(0)
   conn.execute('DELETE FROM correction_groups WHERE id=?', (row[0],))
   conn.commit()
   conn.close()
   print(f'DELETED:{row[1][:80]}')
   " "$HOME/.claude/.claude/epics.db" "<N>"
   ```
3. If output is `NOT_FOUND`, say: "Preference #N does not exist." and stop.
4. Confirm: "Removed preference #N: \"<text snippet (first 80 chars)>\"."

Stop.

---

## Export

Parse optional path after `export`. Default: `"$HOME/.claude/prefs-export.json"`.

1. Run:
   ```bash
   python3 -c "
   import json, sqlite3, sys
   conn = sqlite3.connect(sys.argv[1], timeout=5)
   rows = conn.execute(
       'SELECT theme, source, text, status, count FROM correction_groups WHERE status != ?',
       ('dismissed',)
   ).fetchall()
   conn.close()
   data = [{'theme': r[0], 'source': r[1], 'text': r[2], 'status': r[3], 'count': r[4]} for r in rows]
   with open(sys.argv[2], 'w') as f:
       json.dump(data, f, indent=2)
   print(f'Exported {len(data)} preferences to {sys.argv[2]}')
   " "$HOME/.claude/.claude/epics.db" "<target-path>"
   ```
2. Confirm with the output message.

Stop.

---

## Import

Parse `import <path>` where path is required.

1. If path is empty, say: "Usage: `/prefs import <path>`" and stop.
2. Verify the file exists. If not, say: "File not found: <path>" and stop.
3. Read the JSON file. Validate it is a JSON array of objects each containing at least `theme` and `text` fields. If not, say: "Invalid JSON format. Expected an array of objects with 'theme' and 'text' fields." and stop.
4. Run the import:
   ```bash
   python3 -c "
   import json, sqlite3, sys, time
   with open(sys.argv[2]) as f:
       data = json.load(f)
   conn = sqlite3.connect(sys.argv[1], timeout=5)
   now = int(time.time())
   imported = skipped = 0
   for entry in data:
       existing = conn.execute(
           'SELECT id FROM correction_groups WHERE theme=?', (entry['theme'],)
       ).fetchone()
       if existing:
           skipped += 1
           continue
       conn.execute(
           'INSERT INTO correction_groups (theme, status, source, text, count, created_at, updated_at) '
           'VALUES (?, ?, ?, ?, ?, ?, ?)',
           (entry['theme'], entry.get('status','promoted'), entry.get('source','manual'),
            entry['text'], entry.get('count'), now, now)
       )
       imported += 1
   conn.commit()
   conn.close()
   print(f'Imported {imported} new preferences ({skipped} skipped as duplicates).')
   " "$HOME/.claude/.claude/epics.db" "<path>"
   ```
5. Confirm with the output message.
6. Show the updated list by running the **List** query.

Stop.
