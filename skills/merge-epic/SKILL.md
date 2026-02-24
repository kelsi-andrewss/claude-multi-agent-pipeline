---
name: merge-epic
description: >
  Merge an epic branch into main. Use when the user says "merge epic X"
  or "/merge-epic epic-X". Encodes ORCHESTRATION.md §13 exactly.
  Prerequisite: all stories in the epic must be in closed state.
args:
  - name: epic_ref
    type: string
    description: "Epic ID or slug (e.g. epic-022 or pipeline-self-hosting)."
---

# Merge Epic: {{epic_ref}}

Execute the epic merge sequence per ORCHESTRATION.md §13.

## Steps

1. **Read** `.claude/epics.json`. Find the epic matching `{{epic_ref}}` (match on `id` or derive slug from `branch`). Report if not found and stop.

2. **Verify all stories closed**: Every story in the epic must be in `closed` state. If any are not `closed`, list them and stop — do not proceed until all stories are merged.

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
   - Set the epic state to `closed` in `epics.json` via `update-epics.sh` (or direct node if script absent).
   - Output: "Context checkpoint reached (epic merged). Run /clear to reset the session. All epic and story state is saved in epics.json."

7. **On non-zero exit**: Report the full stdout/stderr to the user. Do not update `epics.json`. The epic branch remains intact until the merge succeeds.
