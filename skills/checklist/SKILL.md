---
name: checklist
description: >
  Run a manual checklist from .claude/checklists/, creating a pipeline story in
  epics.json so progress is tracked cross-session. Supports interactive walk-through
  and direct actions via flags. Use when the user says "/checklist", "/checklist <name>",
  "/checklist <name> status", "/checklist <name> mark <N>", etc.
args:
  - name: checklist_args
    type: string
    description: "Checklist name and optional action: status, mark <N>, unmark <N>, add \"<text>\", remove <N>, reorder <from> <to>, source"
---

# Checklist Skill

Walk through or manage a manual checklist from the project's `.claude/checklists/` directory,
tracking each step in `epics.json` as a story with `agent: "manual"`.

## Flag actions

| Command | Action |
|---|---|
| `/checklist <name>` | Walk interactively (default) |
| `/checklist <name> status` | Numbered steps + progress bar |
| `/checklist <name> mark <N>` | Mark step N done (or text substring match) |
| `/checklist <name> unmark <N>` | Undo completed step |
| `/checklist <name> add "<text>"` | Append step |
| `/checklist <name> add "<text>" --after <N>` | Insert after step N |
| `/checklist <name> remove <N>` | Remove step (confirm first) |
| `/checklist <name> reorder <from> <to>` | Move step position |
| `/checklist <name> source` | Show roadmap provenance |

## Step 1 — Resolve the project root and checklist file

1. Determine the project root: use the current working directory if it contains a
   `.claude/` folder; otherwise walk up until one is found.
2. Glob `<project-root>/.claude/checklists/*.md`.
3. If `/checklist` was called with **no args**:
   - Print: `Available checklists:` followed by each filename stem, one per line.
   - Print: `Run /checklist <name> to start one.`
   - Stop.
4. If args were given: parse the first word as the checklist name, remaining words as action/flags.
   Match name by exact filename stem first, then substring match. If multiple matches, list them
   and ask the user to pick. If zero matches, print `No checklist matching "<name>"
   found in .claude/checklists/` and stop.

## Step 2 — Parse the checklist file

1. Read the matched `.md` file.
2. Check for a source comment: `<!-- source: ... | epic: ... | story: ... -->`. If present, record the provenance.
3. Find the `## Steps` heading. Extract all lines that start with `- [ ]` or `- [x]`
   (in the order they appear). Number them sequentially starting from 1.
4. If no `## Steps` heading or no step lines found, print an error and stop.
5. Count already-completed steps (lines matching `- [x]`).

## Step 3 — Route by action

### Action: `status`

Print:
```
Checklist: <name> (story-NNN, epic-NNN)
Source: <provenance path or "none">

  1. [x] <step text>
  2. [x] <step text>
  3. [ ] <step text>
  4. [ ] <step text>

Progress: [████████░░░░░░░░░░░░] 2/4 (50%)

Actions: /checklist <name> mark 3 | /checklist <name> add "..."
```

Progress bar: 20 chars wide. Filled = `floor(done/total * 20)`. Remainder = `░`.

Stop after printing.

### Action: `mark <N>`

1. Find step N (by number) or by text substring match.
2. If already `[x]`, print "Step N is already complete." and stop.
3. Edit the checklist file: replace `- [ ] <step text>` with `- [x] <step text>`.
4. Print: `[x] Step N marked complete.`
5. Check if all steps are now `[x]`. If so, close the story (see Step 6).

### Action: `unmark <N>`

1. Find step N by number.
2. If already `[ ]`, print "Step N is not yet complete." and stop.
3. Edit the checklist file: replace `- [x] <step text>` with `- [ ] <step text>`.
4. If story was `done`, set it back to `in-progress` via `update-epics.sh`.
5. Print: `[ ] Step N unmarked.`

### Action: `add "<text>"` (with optional `--after <N>`)

1. If `--after <N>` is present: insert `- [ ] <text>` after step N in the file.
2. Otherwise: append `- [ ] <text>` at the end of the steps section.
3. Print: `Added step: <text>`

### Action: `remove <N>`

1. Ask confirmation: `Remove step N: "<text>"? (yes/no)`.
2. On yes: remove the line from the checklist file.
3. Print: `Removed step N.`

### Action: `reorder <from> <to>`

1. Remove step at position `<from>`.
2. Insert it at position `<to>`.
3. Print the updated numbered list.

### Action: `source`

Print the source comment contents if present:
```
Source: .claude/roadmaps/auth-system.md
Epic: epic-005
Story: story-042
```
If no source comment, print "No source provenance recorded."

### Default (no action): interactive walk-through

Proceed to Step 4 (resolve/create story) then Step 5 (walk interactively).

## Step 4 — Resolve or create the story in epics.json

1. Read `<project-root>/.claude/epics.json`.
2. Look for an existing story whose `title` is exactly `"Checklist: <stem>"` and
   whose `state` is not `"done"` or `"shipped"`. If found, resume that story (skip to Step 5).
3. If not found, create the story:
   a. Find or create the Operations epic:
      - Look for an epic titled `"Manual Operations"` in `epics.json`. Use it if found.
      - If not found, assign a new epic ID (increment from the highest existing
        `epic-NNN` number). Epic fields:
        ```json
        {
          "id": "epic-NNN",
          "title": "Manual Operations",
          "branch": null,
          "prNumber": null,
          "persistent": true,
          "state": "active"
        }
        ```
   b. Assign a new story ID (increment from the highest existing `story-NNN` number).
   c. Story fields:
      ```json
      {
        "id": "story-NNN",
        "epicId": "<operations-epic-id>",
        "title": "Checklist: <stem>",
        "state": "in-progress",
        "branch": null,
        "writeFiles": [".claude/checklists/<filename>"],
        "needsTesting": false,
        "needsReview": false,
        "agent": "manual",
        "model": null
      }
      ```
   d. Write to `epics.json` via:
      ```
      bash <project-root>/.claude/scripts/update-epics.sh '<project-root>' '<json-patch>'
      ```
      If `update-epics.sh` does not exist, write directly using a one-line node command.
   e. Print: `Story <story-id> created under "<operations-epic-title>" epic.`

## Step 5 — Walk through steps interactively

For each `- [ ]` step in order (skip `- [x]` steps silently):

1. Print the step text.
2. Ask the user (via `AskUserQuestion`): `"Done? (yes / skip / abort)"`
3. Handle response:
   - **yes** (or "y", "done", "complete"):
     - Edit the checklist file: replace the exact `- [ ] <step text>` line with
       `- [x] <step text>`.
     - Mark the corresponding `TaskCreate` entry as `completed` via `TaskUpdate`.
     - Print: `[x] Step marked complete.`
   - **skip** (or "s"):
     - Leave the checklist file unchanged.
     - Mark the `TaskCreate` entry description with `(skipped)`.
     - Print: `[ ] Step skipped.`
   - **abort** (or "a", "q", "quit", "exit"):
     - Stop immediately. Leave the checklist file and story state as-is.
     - Print:
       ```
       Checklist paused. Story <story-id> is still in-progress.
       Resume with: /checklist <stem>
       ```
     - Stop.

## Step 6 — After all steps are walked through (or all marked via flags)

1. Re-read the checklist file. Count `- [x]` and `- [ ]` lines.
2. **All steps complete** (zero `- [ ]` remaining):
   - Set story state to `done` in `epics.json` (via `update-epics.sh` or direct node write).
   - Print: `Checklist complete. Story <story-id> done.`
3. **Some steps skipped** (one or more `- [ ]` remaining):
   - Set story state to `done` in `epics.json`.
   - Print:
     ```
     Checklist finished with skipped steps. Story <story-id> done.
     Skipped:
       - <step text>
       ...
     ```
4. Print a reminder: `Note: add .claude/checklists/ to your project's .gitignore
   if you don't want checklist files tracked in git.`

## Notes

- Checklist files live in `<project-root>/.claude/checklists/`. This folder is
  **not** created by the skill — the user creates it and populates it with `.md` files.
- The skill does NOT modify `.gitignore`. Remind the user to add the folder themselves.
- Stories with `agent: "manual"` have no worktree, no branch, and no coder. They
  represent human-executed work tracked through the same pipeline as automated stories.
- If `epics.json` does not exist at all, print an error: `No epics.json found at
  <project-root>/.claude/epics.json. Initialize the pipeline first.` and stop.

## Checklist file format (reference)

```markdown
<!-- source: .claude/roadmaps/auth-system.md | epic: epic-005 | story: story-042 -->
# Deploy to Production

## Steps
- [ ] Create API key in provider dashboard (scope: read-only)
- [ ] Add key to .env.production
- [ ] Rotate and revoke the old key
- [ ] Smoke-test the endpoint
```
