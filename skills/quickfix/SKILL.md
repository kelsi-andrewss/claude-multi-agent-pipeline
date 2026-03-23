---
name: quickfix
user_invocable: false
description: >
  Standalone quickfix pipeline: validates criteria, writes plan, launches coder in worktree,
  merges via /merge-worktree. Accepts optional --context flag for artifact chain ingestion
  (upstream clarify/research findings enrich the plan).
args:
  - name: args
    type: string
    description: >
      Description of the fix, with optional --context <path> flag for artifact chain.
---

# Quickfix Skill Invoked

User has requested: `/quickfix {{args}}`

## Flow control

**Continuous execution.** Steps 1 through 9 execute as one uninterrupted flow. Do not pause, narrate, summarize, or ask for confirmation between steps. The only legitimate stop is an error that prevents the next step from running. Parse → validate → read → plan → branch → coder → merge → report — no commentary in between.

---

## Step 1: Parse args

Parse `{{args}}` to extract:

1. **`--context <path>`**: If `--context` appears in args, strip it and the following token. Store the path as `context_path`. Must be a path to a JSON file matching the artifact contract schema.
2. **Remaining text**: The description. Required — if empty after stripping flags, error:
   > "Description required: /quickfix <description>"
3. **Derive slug**: Lowercase the description, replace spaces and non-alphanumeric characters with `-`, collapse consecutive `-`, truncate to max 5 words (e.g., `fix-canvas-zoom-reset`).

```bash
bash ~/.claude/scripts/emit-event.sh "skill.quickfix.started" "claude" "quickfix/${SLUG}" '{"slug":"'"$SLUG"'"}'
```

---

## Step 2: Load artifact chain (only when `context_path` is set)

If `context_path` was not provided, skip to Step 3.

1. Read the JSON file at `context_path`. If it doesn't exist or isn't valid JSON, error:
   > "--context file not found or invalid: <path>"

   Do not fall back — the user explicitly requested context.

2. Validate the artifact has the required fields: `slug`, `scope`, `prev`, `skill`, `data`.

3. **Walk the `prev` chain**: The `prev` field is a path (or null) pointing to the previous artifact. For each non-null `prev`, read that JSON file and collect its `data` payload. Continue walking until `prev` is null. Collect all `data` payloads into a `chain_context` array ordered root-first (earliest ancestor first).

4. **Extract useful context from the chain**:
   - From `.clarify-*.json` artifacts: decisions and constraints
   - From `.research-*.json` artifacts: findings, API shapes, edge cases, test assertions

   Store this as `research_context` for use in Step 5.

---

## Step 3: Validate quickfix criteria

A quickfix is valid when ALL of the following hold:

- **File count**: <=5 write-target files mentioned or implied by the description
- **No breaking schema changes**: Additive field additions OK (new Firestore fields, new optional API params). Renames, deletes, and type changes to existing fields are blocked — use /ship for those.
- **No AI tool changes**: No toolDeclarations, toolExecutors, or system prompt modifications
- **No protected file touches**: Read `<project-root>/.claude/protected-files.md` if it exists. None of the target files appear in the protected list.

If ANY criterion fails, error with the specific reason:
> "Quickfix criteria not met: <reason>. Use /ship for this change."

Do NOT fall back to /ship — that is the orchestrator's decision, not this skill's.

---

## Step 4: Read target files

Identify the 1-5 files the fix will touch. Read them to understand current state. If files don't exist yet, note that — they will be created.

---

## Step 4b: Plan-optional path (<=2 write targets)

If the fix touches **2 or fewer** write-target files, skip Step 5 (plan file writing). Instead, embed the implementation instructions directly into the coder prompt in Step 7.

The embedded instructions must include:
- **Description**: The fix description from Step 1
- **Write targets**: The 1-2 files being modified
- **What to change per file**: Specific changes derived from the description and file reads in Step 4
- **Acceptance criteria**: Observable behavior that confirms the fix

When using this path, the coder prompt in Step 7 replaces `Plan file: plans/<slug>.md` with:

```
Plan file: (inline — no plan file)

## Inline plan

### Description
<description>

### Write targets
| File | Change |
|---|---|
| <file> | <what changes> |

<If research_context exists:>
### Research context
<bullet points from artifact chain>

### Acceptance criteria
- <observable behavior>
```

If the fix touches **3 or more** write-target files, proceed to Step 5 as normal.

---

## Step 5: Write plan file

Write `plans/<slug>.md` with this structure:

```
# <description>

Story: (pending)
Agent: quick-fixer

## Context

<one sentence: what this fixes and why>

<If research_context exists, include the following section:>

## Research context

<Bullet points summarizing relevant findings from the artifact chain — decisions,
constraints, API shapes, edge cases. Reference the source artifact for each item.
Keep it concise — only include findings relevant to this specific fix.>

## What changes

| File | Change |
|---|---|
| <file> | <what changes> |

## Tasks

1. <task 1>
2. <task 2>

## Acceptance criteria

- <observable behavior>

## Verification

- <how to verify>
```

The `## Research context` section is the key enrichment from `--context`. Without it, the plan is identical to a standard quickfix plan.

---

## Step 6: Create branch

```bash
git checkout dev && git checkout -b quickfix/<slug>
```

---

## Step 7: Launch quick-fixer

Launch a `quick-fixer` background agent (model: Sonnet, always) with `run_in_background: true`. The coder prompt creates its own worktree — do NOT use `isolation: "worktree"` on the Agent call (that creates a second, unmanaged worktree that never gets cleaned up).

Use the standard coder prompt from run-stories Step 4:

```
You are executing story (pending): "<description>"

Plan file: plans/<slug>.md
Agent approach: Make surgical, minimal changes. No refactoring beyond what the plan specifies.
Dev branch: dev
Story branch: quickfix/<slug>
Write files scope: <write_files list from plan>
Read-only context files (prefix with worktree path): <read-only context paths, or "none">
Project root: <project-root>

WORKTREE: <project-root>/.claude/worktrees/story/<slug>
All reads and writes MUST use paths under this directory.
Before doing anything else, run: git -C <worktree-path> branch --show-current
Confirm it prints quickfix/<slug>. If not, STOP and report branch mismatch.
Do NOT edit files outside this worktree.

## Tool constraints
You are the coder. Write all code yourself.
Do NOT call any pm_* tools except pm_update_story (for state transitions).

**Gemini MCP — allowed tools:**
- `mcp__gemini__analyze` — use for codebase investigation when you need to understand code outside your write targets. This preserves your context budget: Gemini reads the files and returns a compressed answer instead of you reading 500 lines that produce a one-sentence insight.

**Gemini MCP — blocked tools:** All other `mcp__gemini__*` tools (plan, audit, find_bug, test, gemini_generate, gemini_ui_code, etc.) are orchestrator-only.

**Query format for `analyze`:** Be specific. Include the symbol name, the file paths to examine, and the exact question. Example:
> "In `src/services/orders.ts`, what is the full type signature of `processOrder()` (params + return type), and do any callers in `src/controllers/` depend on the return value? List each caller with the line where the return is used or discarded."
Bad: "What does processOrder do?" — too vague, wastes a round-trip.

## Steps

1. Create the story worktree using direct git commands:

   ```bash
   cd <project-root>
   git fetch origin dev
   git show-ref --verify --quiet "refs/heads/quickfix/<slug>" || git branch "quickfix/<slug>" dev
   git worktree list | grep -q '<worktree-path>' || git worktree add <worktree-path> "quickfix/<slug>"
   ```

2. Verify worktree branch:
   ```bash
   git -C <worktree-path> branch --show-current
   ```
   Must print `quickfix/<slug>`. If not, STOP and report branch mismatch.

3. Read the plan file. Understand what changes are required.

4. Work exclusively inside <worktree-path>. Never edit files in <project-root> directly.

5. Implement the plan: Make surgical, minimal changes. No refactoring beyond what the plan specifies.

6. Stage and commit changes inside the worktree:
   - Stage only the files you modified or created: `git -C <worktree-path> add <file1> <file2> ...`
   - Do NOT use `git add -A` or `git add .`
   - Commit: `git -C <worktree-path> commit -m "quickfix: <slug>"`

7. Push the story branch:
   ```bash
   git -C <worktree-path> push -u origin quickfix/<slug>
   ```

8. Return exactly one of:
   - Success: "DONE: quickfix/<slug> pushed. Commit: <short-hash>. Files changed: <list>. Notes: <any>"
   - Failure: "BLOCKED: <clear reason why the fix could not be completed>"
```

---

## Step 8: On completion

Invoke `/merge-worktree` to diff gate, review, and merge to dev.

### Step 8b: Worktree cleanup guarantee

After Step 8 completes (whether /merge-worktree succeeded or failed), verify the coder's worktree is removed:

```bash
WORKTREE_PATH="<project-root>/.claude/worktrees/story/<slug>"
if [ -d "$WORKTREE_PATH" ]; then
  bash ~/.claude/scripts/worktree-cleanup.sh --worktree-path "$WORKTREE_PATH" --branch "quickfix/<slug>"
fi
```

Also check for any stale agent isolation worktrees from this session:
```bash
for wt in .claude/worktrees/agent-*; do
  [ -d "$wt" ] && git worktree remove --force "$wt" 2>/dev/null
done
```

This catches worktrees left behind when /merge-worktree is bypassed or fails mid-cleanup.

---

## Step 9: Report

```bash
bash ~/.claude/scripts/emit-event.sh "skill.quickfix.completed" "claude" "quickfix/${SLUG}" '{"slug":"'"$SLUG"'"}'
```

On success:
> "Quickfix shipped: quickfix/<slug> -> dev"

On failure, report the coder's BLOCKED reason.
