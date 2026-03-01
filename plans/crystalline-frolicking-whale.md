## Context

The user wants a `/todo` skill that replaces the existing todo-orchestrator flow with a two-phase approach:
1. `/todo <items>` — append raw todo strings to a queue (no planning yet)
2. `/todo plan` — flush the queue to Gemini's `pm_plan_items` for bulk grouping into epics/stories

The queue stores pre-planning raw text — it doesn't belong in the DB yet. A simple `.claude/todos.md` file works: human-readable, easy to edit, and trivial to clear after planning.

`pm_plan_items` has a two-phase flow: Phase 1 produces a proposal (grouped stories), Phase 2 commits on confirmation. The skill needs to drive both phases interactively.

## What changes

**Create `/Users/kelsiandrews/.claude/skills/todo/SKILL.md`** — a single skill file with two modes:

### Mode 1: `/todo <item1>, <item2>, ...` (queue mode)
- Parse `{{args}}`: split on `,` or newlines to get individual items; trim whitespace; drop empty strings
- If `.claude/todos.md` doesn't exist, create it with a header
- Append each item as a bullet: `- <item>` to `.claude/todos.md`
- Print confirmation: "Queued N item(s). Total: M. Run `/todo plan` to send to Gemini."

### Mode 2: `/todo plan` (planning mode)
- Read `.claude/todos.md` — extract all bullet lines (lines starting with `- `)
- If file is empty or missing, stop: "No todos queued. Add some with `/todo <items>` first."
- Load `pm_plan_items` via `ToolSearch` with query `select:mcp__gemini__pm_plan_items`
- Call `pm_plan_items(items=[...], confirmed=False)` → get proposal
- Display the proposal summary (epics, stories, questions from Gemini)
- If proposal has questions, surface them to the user via `AskUserQuestion`
- Ask user to confirm or edit: "Commit this plan to the DB?"
- If confirmed: call `pm_plan_items(items=[...], confirmed=True, proposal=<from phase 1>)`
- Clear `.claude/todos.md` (write empty file or delete)
- Print summary: created epics, stories, tasks

### Mode 3: `/todo list` (view queue)
- Read and print `.claude/todos.md` contents; if empty print "Queue is empty."

### Mode 4: `/todo clear` (reset queue)
- Write empty `.claude/todos.md`; print "Queue cleared."

## Critical files

- **New:** `/Users/kelsiandrews/.claude/skills/todo/SKILL.md`
- **Runtime:** `/Users/kelsiandrews/.claude/.claude/todos.md` (created on first use)
- **MCP tool:** `mcp__gemini__pm_plan_items` in `mcp-servers/gemini/server.py:2282`

## Reuse

- Follow the exact SKILL.md format from `skills/draft-plan/SKILL.md` and `skills/run-stories/SKILL.md`
- Use `ToolSearch` with `select:mcp__gemini__pm_plan_items` before calling the tool (deferred tool pattern)
- Use `AskUserQuestion` for the confirm step (same pattern as `draft-plan`)

## Verification

1. `/todo fix the login bug, add dark mode` → check `.claude/todos.md` has 2 bullet items
2. `/todo add export to PDF` → check `.claude/todos.md` has 3 items total
3. `/todo list` → prints all 3
4. `/todo plan` → Gemini proposal appears, confirm → stories created in DB (`pm_list_stories` shows them), todos.md cleared
5. `/todo plan` again → "No todos queued" message
6. `/todo clear` → file emptied
