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

**DB path:** `~/.claude/.claude/epics.db`

**SQL injection guard:** All user-provided text inserted into SQL must have single quotes escaped by doubling them (`'` to `''`).

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

!`sqlite3 ~/.claude/.claude/epics.db "SELECT printf('%d. [%s] %s', ROW_NUMBER() OVER (ORDER BY updated_at DESC), source, text) FROM correction_groups WHERE (status IN ('promoted','pending_promotion') OR source='manual') AND text != '' ORDER BY updated_at DESC"`

> If the query returns empty output, say: "No preferences found. Use `/prefs add \"<text>\"` to add one."

After the list, show:

```
Commands: /prefs add "<text>" | /prefs edit N "<text>" | /prefs remove N
          /prefs export [path] | /prefs import <path>
```

> If the query errors with "no such column: source" or "no such column: text", say: "The prefs schema hasn't been migrated yet. Run `bash ~/.claude/.claude/scripts/evolve-prefs-schema.sh` first."

Stop.

---

## Add

Parse everything after `add` as the preference text. Strip outer quotes if present.

1. If text is empty, say: "Usage: `/prefs add \"<preference text>\"`" and stop.
2. Sanitize the text (escape single quotes by doubling them).
3. Derive a theme: first 60 characters of text, lowercased.
4. Run:
   ```bash
   sqlite3 ~/.claude/.claude/epics.db "INSERT INTO correction_groups (theme, status, source, text, count, created_at, updated_at) VALUES ('<theme>', 'promoted', 'manual', '<sanitized-text>', NULL, strftime('%s','now'), strftime('%s','now'))"
   ```
5. Shadow to OpenMemory:
   ```bash
   python3 ~/.claude/.claude/hooks/lib/om_write.py "behavioral-pref" "<text>" "global"
   ```
6. Confirm: "Added preference." then show the updated list by running the **List** query.

Stop.

---

## Edit

Parse `edit N "<new text>"` where N is a 1-based row number and the rest is the new text.

1. If N is not a positive integer or text is empty, say: "Usage: `/prefs edit N \"<new text>\"`" and stop.
2. Sanitize the new text. Derive a theme from it.
3. Resolve row number N to the actual `id`:
   ```bash
   sqlite3 ~/.claude/.claude/epics.db "SELECT id FROM correction_groups WHERE (status IN ('promoted','pending_promotion') OR source='manual') AND text != '' ORDER BY updated_at DESC LIMIT 1 OFFSET $((N-1))"
   ```
4. If no row returned, say: "Preference #N does not exist. Run `/prefs list` to see current preferences." and stop.
5. Update:
   ```bash
   sqlite3 ~/.claude/.claude/epics.db "UPDATE correction_groups SET text='<sanitized-text>', theme='<theme>', updated_at=strftime('%s','now') WHERE id=<resolved-id>"
   ```
6. Confirm: "Updated preference #N." then show the updated list by running the **List** query.

Stop.

---

## Remove

Parse `remove N` where N is a 1-based row number.

1. If N is not a positive integer, say: "Usage: `/prefs remove N`" and stop.
2. Resolve row number N to the actual `id` using the same query as Edit step 3.
3. If no row returned, say: "Preference #N does not exist." and stop.
4. Read the text of the row before deleting:
   ```bash
   sqlite3 ~/.claude/.claude/epics.db "SELECT text FROM correction_groups WHERE id=<resolved-id>"
   ```
5. Delete:
   ```bash
   sqlite3 ~/.claude/.claude/epics.db "DELETE FROM correction_groups WHERE id=<resolved-id>"
   ```
6. Confirm: "Removed preference #N: \"<text snippet (first 80 chars)>\"."

Stop.

---

## Export

Parse optional path after `export`. Default: `~/.claude/prefs-export.json`.

1. Run:
   ```bash
   sqlite3 ~/.claude/.claude/epics.db "SELECT json_group_array(json_object('theme',theme,'source',source,'text',text,'status',status,'count',count)) FROM correction_groups WHERE status != 'dismissed'"
   ```
2. Write the JSON output to the target path.
3. Count entries in the JSON array.
4. Confirm: "Exported N preferences to <path>."

Stop.

---

## Import

Parse `import <path>` where path is required.

1. If path is empty, say: "Usage: `/prefs import <path>`" and stop.
2. Verify the file exists. If not, say: "File not found: <path>" and stop.
3. Read the JSON file. Validate it is a JSON array of objects each containing at least `theme` and `text` fields. If not, say: "Invalid JSON format. Expected an array of objects with 'theme' and 'text' fields." and stop.
4. For each entry in the array:
   - Check for existing row with the same theme:
     ```bash
     sqlite3 ~/.claude/.claude/epics.db "SELECT id FROM correction_groups WHERE theme='<sanitized-theme>'"
     ```
   - **If exists:** skip (dedup by theme). Increment skipped count.
   - **If not:** INSERT with the entry's fields. Default `source` to `'manual'`, `status` to `'promoted'`, `created_at` and `updated_at` to now. Increment imported count.
5. Confirm: "Imported N new preferences (M skipped as duplicates)."
6. Show the updated list by running the **List** query.

Stop.
