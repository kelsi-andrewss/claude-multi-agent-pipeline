---
name: checklist
description: >
  Run a manual checklist from .claude/checklists/, creating a pipeline story in
  epics.json so progress is tracked cross-session. Use when the user says
  "/checklist", "/checklist <name>", or "run checklist <name>".
---

# Checklist Skill

Walk through a manual checklist from the project's `.claude/checklists/` directory,
tracking each step in `epics.json` as a story with `agent: "manual"`.

## Step 1 — Resolve the project root and checklist file

1. Determine the project root: use the current working directory if it contains a
   `.claude/` folder; otherwise walk up until one is found.
2. Glob `<project-root>/.claude/checklists/*.md`.
3. If `/checklist` was called with **no args**:
   - Print: `Available checklists:` followed by each filename stem, one per line.
   - Print: `Run /checklist <name> to start one.`
   - Stop.
4. If args were given: match by exact filename stem first (args == stem), then
   substring match (args appear anywhere in filename). If multiple matches, list them
   and ask the user to pick. If zero matches, print `No checklist matching "<args>"
   found in .claude/checklists/` and stop.

## Step 2 — Parse the checklist file

1. Read the matched `.md` file.
2. Find the `## Steps` heading. Extract all lines that start with `- [ ]` or `- [x]`
   (in the order they appear).
3. If no `## Steps` heading or no step lines found, print an error and stop.
4. Count already-completed steps (lines matching `- [x]`).

## Step 3 — Resolve or create the story in epics.json

1. Read `<project-root>/.claude/epics.json`.
2. Look for an existing story whose `title` is exactly `"Checklist: <stem>"` and
   whose `state` is not `"closed"`. If found, resume that story (skip to Step 5).
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
          "persistent": true
        }
        ```
   b. Assign a new story ID (increment from the highest existing `story-NNN` number).
   c. Story fields:
      ```json
      {
        "id": "story-NNN",
        "epicId": "<operations-epic-id>",
        "title": "Checklist: <stem>",
        "state": "running",
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
      If `update-epics.sh` does not exist, write directly using a one-line node command:
      ```bash
      node -e "
        const fs = require('fs');
        const path = '<project-root>/.claude/epics.json';
        const data = JSON.parse(fs.readFileSync(path, 'utf8'));
        // add epic if new
        // add story
        fs.writeFileSync(path, JSON.stringify(data, null, 2));
      "
      ```
      Construct the node command inline with the actual values substituted.
   e. Print: `Story <story-id> created under "<operations-epic-title>" epic.`

## Step 4 — Create TaskCreate entries for uncompleted steps

For each `- [ ]` step (not yet completed), call `TaskCreate` with:
- `title`: the step text (stripped of `- [ ] ` prefix)
- `description`: `Checklist: <stem> — step N of M`

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
       Checklist paused. Story <story-id> is still running.
       Resume with: /checklist <stem>
       ```
     - Stop.

## Step 6 — After all steps are walked through

1. Re-read the checklist file. Count `- [x]` and `- [ ]` lines.
2. **All steps complete** (zero `- [ ]` remaining):
   - Set story state to `closed` in `epics.json` (via `update-epics.sh` or direct node write).
   - Print: `Checklist complete. Story <story-id> closed.`
3. **Some steps skipped** (one or more `- [ ]` remaining):
   - Set story state to `closed` in `epics.json`.
   - Print:
     ```
     Checklist finished with skipped steps. Story <story-id> closed.
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
# Deploy to Production

## Steps
- [ ] Create API key in provider dashboard (scope: read-only)
- [ ] Add key to .env.production
- [ ] Rotate and revoke the old key
- [ ] Smoke-test the endpoint
```
