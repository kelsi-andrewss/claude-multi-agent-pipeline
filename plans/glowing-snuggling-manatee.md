# Context

The `/find-bug` skill currently calls `mcp__gemini__find_bug` and prints the result only. The user wants it to also write the diagnosis to `plans/` and create a tracking story — matching the `draft-plan` workflow pattern.

The previous implementation did all the work inline in the skill steps. The correct pattern (per `draft-plan`) is to delegate writing and PM calls to a **background `general-purpose` agent**, keeping the skill as a thin orchestrator.

---

# Plan

## What changes

### File: `skills/find-bug/SKILL.md`

Replace steps 4–6 with a single background agent delegation step, matching `draft-plan`'s Step 4 pattern exactly.

**Step 4 — Load PM tools (required before delegation)**

Call `ToolSearch` with query `mcp__gemini__pm` to load the deferred PM tools. This must happen in the foreground before launching the agent, since the agent needs `pm_list_epics`, `pm_create_story`, `pm_set_plan_file`, and optionally `pm_create_epic`.

**Step 5 — Ask about epic (foreground, interactive)**

Call `mcp__gemini__pm_list_epics` to get active epics.

- **If active epics exist:** Use `AskUserQuestion` to ask the user which epic to assign — present the list plus "Create new epic" and "No epic (backlog)".
- **If none:** Silently proceed with `epic_id = null`.

(This must happen in the foreground because it's interactive.)

**Step 6 — Launch background agent**

Launch one `general-purpose` agent with `run_in_background: true`. Pass it:

```
You are writing a bug diagnosis plan file and creating a tracking story.

Symptom: <symptom>

Gemini diagnosis:
<full find_bug output>

Epic choice: <epic_id or "null" or "CREATE_NEW: <title>">

Tasks:
1. Glob plans/*.md to find existing plan files and avoid name collisions.
   Generate a whimsical <adjective>-<gerund>-<noun> name not in use.

2. Write plans/<name>.md:
   # Bug Diagnosis: <symptom truncated to ~60 chars>

   <full Gemini output verbatim>

3. If epic choice is "CREATE_NEW: <title>": call pm_create_epic(title=<title>)
   and use the returned epic_id. Otherwise use the provided epic_id (may be null).

4. Extract from the diagnosis:
   - Root cause summary: one-sentence after "Root cause:" → story title "Fix: <root cause>"
   - File paths under "### Most likely location" → write_files list

5. Call pm_create_story(
     title="Fix: <root cause summary>",
     epic_id=<chosen epic_id or null>,
     agent="architect",
     write_files=[<extracted paths>]
   )

6. Call pm_set_plan_file(story_id=<new story id>, plan_file="plans/<name>.md")

7. Return exactly:
   "Done: plans/<name>.md written. Story <story-id> created in <epic-id or backlog>."
```

**Step 7 — Report results**

After the background agent completes, print:

```
Diagnosis written to: plans/<name>.md

Story created: <story-id> — <title>
  Epic: <epic-id> (<epic title>) or Backlog

Next step: /run-stories <story-id>
  or review the plan at plans/<name>.md
```

---

## Critical files

| File | Change |
|------|--------|
| `skills/find-bug/SKILL.md` | Replace inline steps 4–6 with foreground epic picker + background agent delegation |

No changes to `mcp-servers/gemini/server.py` — all needed MCP tools already exist.

---

## Key difference from previous version

The previous implementation called `Glob`, `Write`, `pm_create_story`, and `pm_set_plan_file` directly in the skill steps. The correct pattern (per `draft-plan`) is:
- **Foreground**: only interactive steps (epic picker via `AskUserQuestion`)
- **Background agent**: all file writing and PM calls

---

## Verification

1. Run `/find-bug <symptom>` on a real codebase
2. Confirm `plans/<whimsical-name>.md` is created with the diagnosis
3. Confirm `pm_board` shows the story with the plan file linked
4. If a new epic was created, confirm it shows in `pm_list_epics`
5. Verify `pm_get_story <story-id>` returns the correct `plan_file` path
