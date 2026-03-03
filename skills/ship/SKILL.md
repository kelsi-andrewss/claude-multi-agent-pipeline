---
name: ship
description: "One-shot pipeline: idea to running coders in a single command. Creates epic, stories, tasks, plan files, and launches execution. Use when the user says \"/ship <title> <features>\", \"/ship path/to/prd.md\", \"/ship plans/existing-plan.md\", or \"/ship epic-NNN\"."
args:
  - name: args
    type: string
    description: "Title + feature list, PRD file path, plan file path, or epic ID."
---

# Ship Skill Invoked

User has requested: `/ship {{args}}`

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to determine the mode:

1. **Resume mode**: first token matches `epic-\d+` → set `epic_id` to that token.
2. **File mode**: a token ends with `.md` and the file exists → read it:
   - If path starts with `plans/` and file contains `## What changes` → **Execute mode** (existing plan file).
   - Otherwise → **PRD mode** (requirements doc). Read file contents as `context`.
3. **Inline mode**: everything else. Extract:
   - Quoted string or text before numbered items → `title`
   - `by YYYY-MM-DD` → `target_date`
   - Remaining numbered or comma-separated items → `items` list
4. **No args**: Ask the user: "Describe what to build (features or file path):" and stop.

---

## Step 1: Load tool

```
ToolSearch: select:mcp__gemini__pm_ship
```

---

## Step 2: Call pm_ship (one tool call)

Based on mode:

- **Inline mode**: `pm_ship(items=[...], title="...", target_date=<or null>)`
- **PRD mode**: `pm_ship(items=[...extracted feature lines...], title="...", context=<file contents>)`
- **Resume mode**: `pm_ship(items=[], epic_id="epic-NNN")`
- **Execute mode**: Skip pm_ship entirely. Go to Step 2b.

### Step 2b: Execute mode (existing plan file)

For an existing plan file:
1. Read the plan file.
2. Extract the title from the first `# ` heading.
3. Load `ToolSearch: select:mcp__gemini__pm_create_story`
4. Call `pm_create_story(title=<extracted title>, agent="architect")`.
5. Load `ToolSearch: select:mcp__gemini__pm_update_story`
6. Call `pm_update_story(story_id=<new story id>, plan_file="<plan file path>")`.
7. Go to Step 4 with that single story ID.

---

## Step 3: Write plan files (Claude's job)

From the `pm_ship` response, for each story in the `stories` array:

1. Generate a plan file name: `plans/<random-adjective-noun>.md`
2. Write the plan file with this structure:
   ```
   # <story title>

   Story: <story_id>
   Agent: <agent>

   ## Context

   <Brief description of what this story accomplishes>

   ## What changes

   | File | Change |
   |---|---|
   | <write_file> | <description from tasks> |

   ## Tasks

   1. <task 1>
   2. <task 2>
   ...

   ## Verification

   - <how to verify the changes work>
   ```
3. Load `ToolSearch: select:mcp__gemini__pm_update_story`
4. Call `pm_update_story(story_id=<id>, plan_file="plans/<name>.md")` for each story.

---

## Step 4: Execute

Collect all story IDs (space-separated) and invoke:

```
Skill: run-stories, args: "<story-id-1> <story-id-2> ..."
```

---

## Step 5: Report

After `/run-stories` completes, print a summary:
```
Shipped: <epic title> (<epic_id>)
  story-NNN: <title> — <agent> — plan: plans/<name>.md
  ...

Stories are running in background worktrees.
Use /roadmap to check progress.
```
