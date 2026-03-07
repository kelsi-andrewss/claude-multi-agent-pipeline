---
name: todo
description: "Two-phase todo queue: append raw items to .claude/todos.md, then bulk-plan them via Gemini's pm_plan_items. Use when the user says \"/todo <items>\", \"/todo plan\", \"/todo list\", or \"/todo clear\"."
args:
  - name: args
    type: string
    description: "Subcommand and/or raw todo items."
---

# Todo Skill Invoked

User has requested: `/todo {{args}}`

---

## Subcommand dispatch

Parse the first token of `{{args}}`:

- `plan` → go to **Phase 2: Plan**
- `list` → print contents of `.claude/todos.md` and stop
- `clear` → delete `.claude/todos.md` and confirm, then stop
- anything else (including no args) → go to **Phase 1: Append**

---

## Phase 1: Append

Treat all of `{{args}}` as raw todo text (one item, or a newline/comma-separated list).

1. Read `.claude/todos.md` if it exists (create if not).
2. Append each item as a new line in the format:
   ```
   - <item text>
   ```
3. Write the file back.
4. Print the current queue to the user:
   ```
   Added N item(s). Current queue (.claude/todos.md):
   - item 1
   - item 2
   ...

   Run `/todo plan` to bulk-plan all queued items.
   ```
5. Stop.

---

## Phase 2: Plan

1. Read `.claude/todos.md`. If empty or missing, tell the user the queue is empty and stop.

2. Parse all `- <item>` lines into a list of strings.

3. Load the Gemini planning tool:
   ```
   ToolSearch: select:mcp__gemini__pm_plan_items
   ```

4. Call `pm_plan_items(items=[...], confirmed=False)` with the full list.
   - This returns a proposal summary; read the detail file for the full grouping into epics/stories/tasks.

5. Display the proposal to the user in a readable summary:
   ```
   Proposed plan:

   Epic: <epic title>
     story-NNN: <story title>
       - task 1
       - task 2
     story-NNN: <story title>
       ...
   ```

6. Delegate the heavy commit call to the **planner** agent (foreground):

   ```
   Agent(subagent_type="planner", prompt="""
   MODE: todo-plan
   TODO_ITEMS: <items list from step 2>
   PROPOSAL_ID: <proposal_id from step 4>
   """)
   ```

   **On PLANNER_RESULT**: Extract story IDs from the result.
   **On PLANNER_ERROR**: Surface the error to the user. Do NOT fall back to direct MCP calls.

7. Delete `.claude/todos.md`.
   - Collect story IDs from the PLANNER_RESULT.
   - Immediately invoke `/draft-plan <story-ids>` (space-separated). Do not ask.
