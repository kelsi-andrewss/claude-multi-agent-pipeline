---
name: quick
description: >
  Lightweight pipeline bypass for small iterative changes. Works directly in
  the main worktree on a persistent `quickfix` branch (no worktree created).
  Records each change as a story in the `epic-quickfix` epic in epics.json.
  Supports --merge to squash-merge to main.
args:
  - name: description
    type: string
    description: >
      Description of the change. Append flags as needed:
        --no-epic       skip epics.json entry, commit as "fix: <description>"
        --to-branch <n> target branch other than "quickfix"
        --merge         merge mode: squash quickfix → main, delete branch, reset epic
---

# Quick: {{description}}

Lightweight pipeline bypass per ORCHESTRATION.md §quickfix.

## Parse args

Extract `description` and flags from `{{description}}`:

- `--merge` — if present, skip to Merge Steps below
- `--no-epic` — skip epics.json entry entirely
- `--to-branch <name>` — use `<name>` instead of `quickfix` as the target branch (default: `quickfix`)

Strip all flags from `description` before using it as the commit/story title.

## Safety rails (always enforced, even with --no-epic)

Run `git status --porcelain` to see staged files.

**Hard stop — protected files**: If any of the following files appear in staged output, stop immediately with an error:
- `BoardCanvas.jsx`
- `StickyNote.jsx`
- `Frame.jsx`
- `Shape.jsx`
- `LineShape.jsx`
- `Cursors.jsx`

**Firestore schema warning**: If `firestore.rules` or any file matching `*migration*` appears in staged output, warn the user: "Warning: /quick does not support Firestore schema changes. Proceed manually or use /todo."

**File count check**: Count total files in staged output.
- If N > 3 and N < 5: warn "Quick fix touching N files — consider /todo for better isolation."
- If N >= 5: hard stop — "Too many files for /quick (N). Use /todo instead." Do not proceed.

## Step 1 — epics.json update (skip if --no-epic)

Read `.claude/epics.json`.

Find the `epic-quickfix` epic in the `epics` array (matching `id: "epic-quickfix"`). If not found, add it:

```json
{
  "id": "epic-quickfix",
  "title": "Quick fixes",
  "persistent": true,
  "branch": null,
  "prNumber": null,
  "stories": []
}
```

Auto-increment the next story ID: scan all epics for the highest numeric story ID across all stories, add 1. Format as `story-NNN` (zero-padded to 3 digits).

Create the story object:

```json
{
  "id": "<next-story-id>",
  "epicId": "epic-quickfix",
  "title": "<description>",
  "state": "closed",
  "branch": "<target-branch>",
  "writeFiles": [],
  "needsTesting": false,
  "needsReview": false
}
```

Write the updated epics.json using a node inline command:

```bash
node -e "
const fs = require('fs');
const path = '.claude/epics.json';
const data = JSON.parse(fs.readFileSync(path, 'utf8'));
const qfEpic = data.epics.find(e => e.id === 'epic-quickfix');
if (qfEpic) {
  qfEpic.stories.push(<story-object-json>);
} else {
  data.epics.push({ id: 'epic-quickfix', title: 'Quick fixes', persistent: true, branch: null, prNumber: null, stories: [<story-object-json>] });
}
fs.writeFileSync(path, JSON.stringify(data, null, 2) + '\n');
"
```

Record `<next-story-id>` for use in the commit message.

## Step 2 — ensure target branch

Check if target branch exists:

```bash
git show-ref --verify --quiet refs/heads/<target-branch>
```

If exit code is non-zero (branch does not exist):

```bash
git checkout -b <target-branch> main
```

Do NOT create a git worktree. This operates directly in the main worktree.

## Step 3 — check out target branch

```bash
git checkout <target-branch>
```

## Step 4 — check for staged changes

Run `git status --porcelain` to check for staged files (lines starting with a letter in the first column, e.g. `M `, `A `, `D `).

If NO staged changes are present, instruct the user:

> Make your changes now. When done, stage the files and re-run `/quick <description>` (with changes staged) to commit.

Stop here and wait for user to stage changes.

If staged changes ARE present, proceed to Step 5.

## Step 5 — commit

Stage any modified (not yet staged) files that are part of the change if the user has unstaged tracked modifications:

```bash
git add -u
```

Commit:

- Without `--no-epic`: `git commit -m "fix(<story-id>): <description>"`
- With `--no-epic`: `git commit -m "fix: <description>"`

## Step 6 — update writeFiles in epics.json (skip if --no-epic)

Get the list of files from the commit:

```bash
git diff-tree --no-commit-id -r --name-only HEAD
```

Update the story's `writeFiles` field in epics.json using a node inline command (same pattern as Step 1, find the story by ID and set its `writeFiles` array).

## Step 7 — return to main

```bash
git checkout main
```

## Step 8 — report

Report:
- Story ID (if not --no-epic)
- Files changed (list)
- Commit hash (`git rev-parse --short HEAD` on the target branch before switching back — capture before checkout)
- Branch: `<target-branch>`

---

## Merge Steps (triggered by --merge flag)

### Step 9 — read epic-quickfix stories

Read `.claude/epics.json`. Find `epic-quickfix`. Get all stories in the `stories` array, sorted ascending by numeric ID.

Determine target branch: `quickfix` (default) or `--to-branch` value if provided with `--merge`.

### Step 10 — build commit map

Run:

```bash
git log <target-branch> --oneline
```

Build a map from story ID to commit hash by matching commit messages of format `fix(<story-id>):` against the stories list. Stories without a matching commit are skipped with a warning.

### Step 11 — cherry-pick onto main

Ensure you are on main:

```bash
git checkout main
```

For each story in ascending ID order, cherry-pick its commit:

```bash
git cherry-pick <commit-hash>
```

If a cherry-pick fails (conflict):

```bash
git cherry-pick --abort
```

Report: "Cherry-pick conflict on <story-id> (<description>). Conflicting files: <list>. Resolve manually and re-run `/quick --merge`."

Stop. Do not auto-resolve conflicts.

### Step 12 — cleanup on success

After all cherry-picks succeed:

Delete the quickfix branch:

```bash
git branch -d quickfix
```

Reset epic-quickfix stories list in epics.json to `[]` (keep the epic object itself):

```bash
node -e "
const fs = require('fs');
const path = '.claude/epics.json';
const data = JSON.parse(fs.readFileSync(path, 'utf8'));
const qfEpic = data.epics.find(e => e.id === 'epic-quickfix');
if (qfEpic) { qfEpic.stories = []; }
fs.writeFileSync(path, JSON.stringify(data, null, 2) + '\n');
"
```

### Step 13 — merge report

Report:
- N stories merged (list titles and commit hashes)
- quickfix branch deleted
- epic-quickfix stories list reset
