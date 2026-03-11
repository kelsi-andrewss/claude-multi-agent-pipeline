---
name: quickfix
description: >
  Standalone quickfix pipeline: validates criteria, writes plan, launches coder in worktree,
  merges via /merge-worktree. Accepts optional --context flag for artifact chain ingestion
  (upstream clarify/research findings enrich the plan).
  Use when the user says "/quickfix <description>" or "/quickfix --context path/to/artifact.json <description>".
args:
  - name: args
    type: string
    description: >
      Description of the fix, with optional --context <path> flag for artifact chain.
---

# Quickfix Skill Invoked

User has requested: `/quickfix {{args}}`

---

## Step 1: Parse args

Parse `{{args}}` to extract:

1. **`--context <path>`**: If `--context` appears in args, strip it and the following token. Store the path as `context_path`. Must be a path to a JSON file matching the artifact contract schema.
2. **Remaining text**: The description. Required — if empty after stripping flags, error:
   > "Description required: /quickfix <description>"
3. **Derive slug**: Lowercase the description, replace spaces and non-alphanumeric characters with `-`, collapse consecutive `-`, truncate to max 5 words (e.g., `fix-canvas-zoom-reset`).

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

- **File count**: <=3 write-target files mentioned or implied by the description
- **No schema changes**: No Firestore field additions, no DB migrations, no API contract changes
- **No AI tool changes**: No toolDeclarations, toolExecutors, or system prompt modifications
- **No protected file touches**: Read `<project-root>/.claude/protected-files.md` if it exists. None of the target files appear in the protected list.

If ANY criterion fails, error with the specific reason:
> "Quickfix criteria not met: <reason>. Use /ship for this change."

Do NOT fall back to /ship — that is the orchestrator's decision, not this skill's.

---

## Step 4: Read target files

Identify the 1-3 files the fix will touch. Read them to understand current state. If files don't exist yet, note that — they will be created.

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

Launch a `quick-fixer` background agent (model selection: Sonnet by default; Haiku only if ALL Haiku threshold criteria from ORCHESTRATION SS2 are met — never Haiku for pipeline files) in a worktree on `quickfix/<slug>` with the plan file as input.

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
Do NOT call any mcp__gemini__* tools (gemini_generate, gemini_chat, analyze, audit, find_bug, plan, test, etc.).
Do NOT call any pm_* tools except pm_update_story (for state transitions).
Gemini is a research tool for the orchestrator — not available to coders.

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

**Model-specific warning for Haiku** (append to agent-approach when using Haiku):
> "CRITICAL: PRESERVE existing patterns. When extending or expanding code (regexes, arrays, switch cases, config objects), ADD new entries — never replace the existing block wholesale. Read the target section first, then insert your additions alongside what's already there."

---

## Step 8: On completion

Invoke `/merge-worktree` to diff gate, review, and merge to dev.

---

## Step 9: Report

On success:
> "Quickfix shipped: quickfix/<slug> -> dev"

On failure, report the coder's BLOCKED reason.
