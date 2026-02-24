---
name: lint
description: >
  Run the project linter against a story's worktree. Quick pre-merge
  sanity check without running the full unit-tester pipeline. Use when
  the user says "/lint", "/lint story-X", or "lint story X".
args:
  - name: story_id
    type: string
    description: "Optional story ID to lint (e.g. story-042). If omitted, uses the current working directory."
---

# Lint: {{story_id}}

## Steps

1. **Resolve worktree path**:
   - If `{{story_id}}` is provided: read `.claude/epics.json`, find the story, get its `branch` field, then find the matching path from `git worktree list`.
   - If no story ID: use the current working directory as the project root.
   - If the story is not found or has no worktree, stop and report.

2. **Detect linter**:
   Check for a lint script in the worktree's `package.json`:
   ```bash
   node -e "const p=require('./package.json'); console.log(p.scripts && p.scripts.lint ? 'yes' : 'no')" 2>/dev/null
   ```
   - If no lint script found: output "No linter configured in package.json. Skipping." and stop.

3. **Run linter**:
   ```bash
   npm run lint --prefix <worktree-path>
   ```

4. **Report results**:
   - **No errors**: output "Lint passed — no errors."
   - **Errors**: surface all error lines inline. Output "Lint FAILED — <N> error(s). Fix before merging."
   - **Warnings only**: output "Lint passed with <N> warning(s)." List warnings. Do not block.

5. **Exit codes**:
   - Lint errors → FAIL (report, do not auto-fix)
   - Lint warnings → PASS with warnings surfaced
   - No linter → SKIP (informational only)
