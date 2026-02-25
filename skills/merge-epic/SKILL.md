---
name: merge-epic
description: >
  Merge an epic branch into main. Use when the user says "merge epic X"
  or "/merge-epic epic-X". Encodes ORCHESTRATION.md §13 exactly.
  Prerequisite: all stories in the epic must be in done state (unless --partial).
  Supports --partial flag to merge done stories and move open stories to a continuation epic.
args:
  - name: epic_ref
    type: string
    description: "Epic ID or slug (e.g. epic-022 or pipeline-self-hosting). Optionally append --partial."
---

# Merge Epic: {{epic_ref}}

Execute the epic merge sequence per ORCHESTRATION.md §13.

## Parse flags

If `--partial` is present in `{{epic_ref}}`:
- Extract the epic ID/slug (everything before `--partial`)
- Enable partial merge mode (see Partial Merge section below)

## Steps (full merge — default)

1. **Read** `.claude/epics.json`. Find the epic matching `{{epic_ref}}` (match on `id` or derive slug from `branch`). Report if not found and stop.

2. **Verify all stories done**: Every story in the epic must be in `done` state. If any are not `done`, list them and stop — do not proceed until all stories are merged.

3. **Resolve `prNumber`**: Read the epic's `prNumber` from `epics.json`. If null or empty, report "No epic PR found — run /merge on outstanding stories first." and stop.

4. **Draft → ready conversion**: Check whether the epic PR is a draft:
   ```
   gh pr view <prNumber> --json isDraft
   ```
   If `isDraft` is `true`, run:
   ```
   gh pr ready <prNumber>
   ```
   Wait for it to succeed before proceeding. If it fails, report the error and stop.

5. **Launch git-ops** (background) with prompt:
   ```
   Run: bash <project-root>/.claude/scripts/merge-epic.sh \
     <project-root> <epic-slug> <pr-number>
   Report exit code and full stdout/stderr. Do not edit any files.
   ```

6. **On exit 0**:
   - Set the epic state to `shipped` in `epics.json` via `update-epics.sh`.
   - Set all stories in the epic to `shipped` via `update-epics.sh`.
   - Output: "Context checkpoint reached (epic merged). Run /clear to reset the session. All epic and story state is saved in epics.json."

7. **On non-zero exit**: Report the full stdout/stderr to the user. Do not update `epics.json`. The epic branch remains intact until the merge succeeds.

## Partial Merge (`--partial`)

1. **Read** `.claude/epics.json`. Find the epic. Report if not found and stop.

2. **Verify at least one story is `done`**. If none are done, print "No done stories to merge. Run /merge on stories first." and stop.

3. **List open stories** (any state other than `done`):
   ```
   Open stories that will NOT be merged:
     story-NNN  [in-progress]  <title>
     story-NNN  [draft]        <title>
   ```
   Ask via `AskUserQuestion`: "Proceed with partial merge? (yes/no)"

4. **On yes**:
   a. Resolve `prNumber` and do draft → ready conversion (same as full merge steps 3-4).
   b. Launch git-ops for `merge-epic.sh` (background). On exit 0:
   c. Set `done` stories to `shipped`.
   d. Set original epic state to `shipped`.
   e. Create a **continuation epic**:
      ```json
      {
        "id": "epic-NNN",
        "title": "<original title> (cont)",
        "branch": null,
        "prNumber": null,
        "persistent": true,
        "state": "active"
      }
      ```
   f. Move all open stories to the continuation epic (update `epicId`).
   g. Note to user which branches need rebasing onto main:
      ```
      Continuation epic created: <epic-id> — <title> (cont)
      Stories moved: <list>
      Note: story branches may need rebasing onto main.
      ```

5. **On no**: Stop without changes.
