---
name: promote-learning
description: >
  Promote entries from reviewer-learnings.md into CLAUDE.md. Use when the
  user says "/promote-learning", "promote learnings", "review learnings", or
  "promote reviewer learnings". Interactive — asks yes/no/edit per entry.
  Writes to the project's .claude/reviewer-learnings.md and ~/.claude/CLAUDE.md.
---

# Promote Reviewer Learnings

Read `reviewer-learnings.md` in the current project's `.claude/` directory,
display all entries grouped by category, and interactively promote them to
`~/.claude/CLAUDE.md`.

## Step 1 — locate files

Determine the project root: look for a `.claude/reviewer-learnings.md` file
starting from the current working directory. If not found, report
"No reviewer-learnings.md found in .claude/" and stop.

The target for promoted entries is `~/.claude/CLAUDE.md` (the user's global
instructions file).

## Step 2 — parse entries

Read `.claude/reviewer-learnings.md`. Entries follow this format:

```
## <category>

- <entry text>
<!-- reviewed -->   ← already processed; skip unless --all flag given
```

Group entries by their `## <category>` heading. Ignore entries that already
have a `<!-- reviewed -->` marker on the following line (they were handled in
a prior session).

If all entries are already marked reviewed, report "All entries already
reviewed. Nothing to promote." and stop.

## Step 3 — display and prompt

For each unreviewed entry, in category order:

1. Print the category header and the entry text.
2. Use AskUserQuestion to ask:
   "Promote this entry to CLAUDE.md? Enter: yes / no / edit"

Handle each response:

- **yes** — append the entry as a bullet point under the matching section in
  `~/.claude/CLAUDE.md`. If a section heading matching the category exists,
  append under it. If no matching section exists, append a new `## <category>`
  section at the end of the file followed by the bullet. Mark the entry as
  reviewed in `reviewer-learnings.md` by appending `<!-- reviewed -->` on the
  line immediately after the bullet.

- **no** — mark the entry as reviewed in `reviewer-learnings.md` by appending
  `<!-- reviewed -->` on the line immediately after the bullet. Do not write
  anything to CLAUDE.md.

- **edit** — use AskUserQuestion to ask: "Enter the edited text for this
  entry:" then treat the user's response as the new entry text and follow the
  **yes** path using the edited text. Mark the original entry as reviewed.

## Step 4 — report summary

After all entries are processed, print:

```
Done. N promoted, N skipped.
```

## Step 5 — optional cleanup

Use AskUserQuestion to ask:
"Remove all reviewed entries from reviewer-learnings.md? (yes/no)"

- **yes** — rewrite `reviewer-learnings.md` keeping only unreviewed entries
  and their category headings. Remove any category heading that has no
  remaining entries.
- **no** — leave the file as-is with `<!-- reviewed -->` markers intact.

## Notes

- Do NOT overwrite existing content in CLAUDE.md — only append to or extend it.
- Matching a CLAUDE.md section to a category is case-insensitive and
  ignores leading/trailing whitespace.
- If reviewer-learnings.md is empty after removing reviewed entries, delete
  the file rather than leaving an empty file.
- This skill is interactive and must run in the foreground — do NOT launch it
  with run_in_background.
