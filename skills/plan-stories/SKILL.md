---
name: plan-stories
description: >
  Bridge between presearch briefings (or inline args) and the /draft-plans skill.
  Parses inputs, dispatches the planner agent to create an epic and stories in the DB,
  and writes .ship-manifest.json for downstream consumption. Three invocation modes:
  briefing path, inline title+items, or resume an existing epic. Also handles execute
  mode for existing plan files (bypasses planner, creates DB entries directly).
  Use when the user says "/plan-stories presearch/topic.md",
  "/plan-stories \"Title\" 1. Feature 2. Feature", or "/plan-stories epic-NNN".
args:
  - name: args
    type: string
    description: "Briefing file path, inline title + feature items, epic ID (epic-NNN), or existing plan file path."
---

# Plan Stories Skill Invoked

User has requested: `/plan-stories {{args}}`

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to determine the mode. This skill does NOT handle orchestrator flags (--quick, --argue, --quickfix) -- those belong to /ship.

1. **Resume mode**: first token matches `epic-\d+` -- set `epic_id` to that token.

2. **File mode**: a token ends with `.md` and the file exists -- read it:
   - If file contains `## What changes` -- **Execute mode** (existing plan file). Go to Step 1.
   - If file contains `## Summary` -- **Briefing mode** (presearch output). Extract:
     - `briefing_path` = the file path
     - `briefing_contents` = full file contents
     - `items` = numbered items from `## Features` > `### MVP` (skip item 0 Bootstrap)
     - `title` = first `# ` heading
   - Otherwise -- treat file contents as context, extract title from first `# ` heading.

3. **Inline mode**: everything else. Extract:
   - Quoted string or text before numbered items -- `title`
   - Remaining numbered or comma-separated items -- `items` list

4. **No args**: Ask the user: "What should I plan? Provide a briefing path, title + features, or epic ID." and stop.

---

## Step 1: Execute mode (existing plan file)

**Run only when Execute mode was detected in Step 0. All other modes skip to Step 2.**

The `.md` file contains `## What changes` -- this is an existing plan. Bypass the planner entirely.

1. Read the plan file and parse:
   - **Title**: first `# ` heading
   - **Agent**: value from `Agent:` line (default: `architect`)
   - **Write targets**: file paths from the first column of the `## What changes` table (skip header row and `|---|` separator)

2. Load tools:
   ```
   ToolSearch: select:mcp__gemini__pm_create_story,mcp__gemini__pm_update_story,mcp__gemini__pm_create_epic
   ```

3. **Route by scope:**

   **Quick-fix path (<=2 write targets):**
   - No epic -- omit `epic_id` (story lands in `epic-backlog`)
   - Agent: parsed `Agent:` line, or `quick-fixer`
   - `pm_create_story(title=<title>, agent=<agent>, write_files=<write targets>)`
   - `pm_update_story(story_id=<new id>, plan_file="<plan file path>")`
   - Set `stories` = single-element list with the created story
   - Set `epic_id` = null, `dev_branch` = null

   **Full path (>2 write targets):**
   - `pm_create_epic(title=<title>)` -- use returned `epic_id`
   - Agent: parsed `Agent:` line, or `architect`
   - `pm_create_story(title=<title>, epic_id=<epic_id>, agent=<agent>, write_files=<write targets>)`
   - `pm_update_story(story_id=<new id>, plan_file="<plan file path>")`
   - Set `stories` = single-element list with the created story
   - Derive `dev_branch` from epic metadata

4. Skip to Step 3.

---

## Step 2: Dispatch planner agent (foreground)

**Run for briefing mode, inline mode, and resume mode.**

Launch the **planner** agent in foreground with the parsed inputs:

**For briefing mode and inline mode:**

```
Agent(subagent_type="planner", prompt="""
MODE: ship
TITLE: <title>
ITEMS: <items list>
CONTEXT: <briefing_contents if briefing mode, otherwise omit>

DECOMPOSITION RULE: Minimize write-target file overlap across stories. Group changes by the files they modify, not by conceptual theme or tier. A story that owns a file implements ALL changes to that file across all features in the epic. If two stories would share a write-target file, restructure them to eliminate the overlap — every shared file serializes those stories and kills parallelism. Decomposition priority: file ownership > conceptual grouping.
""")
```

**For resume mode:**

```
Agent(subagent_type="planner", prompt="""
MODE: ship
EPIC_ID: epic-NNN

DECOMPOSITION RULE: Minimize write-target file overlap across stories. Group changes by the files they modify, not by conceptual theme or tier. A story that owns a file implements ALL changes to that file across all features in the epic. If two stories would share a write-target file, restructure them to eliminate the overlap — every shared file serializes those stories and kills parallelism. Decomposition priority: file ownership > conceptual grouping.
""")
```

Wait for the planner to return.

**On PLANNER_RESULT**: Extract `epic_id`, `dev_branch`, and the story list (IDs, titles, agents, detail_file paths). Proceed to Step 3.

**On PLANNER_ERROR**: Surface the error to the user with full details (step, tool, error message, partial results). Do NOT fall back to direct MCP calls -- the failure causes (MCP down, Gemini garbage, agent context limit) would also fail here. Do NOT write a manifest. Let the user decide: retry, adjust input, or abort. Stop.

---

## Step 3: Write .ship-manifest.json

Build the manifest from the data collected in Step 1 (execute mode) or Step 2 (planner result).

**Derive slug**: from title -- lowercase, hyphen-separated, max 40 chars.

**Complexity heuristic**:
- small = 1 story
- medium = 2-4 stories
- large = 5+ stories

**Estimated file count**: sum of write-target counts across all stories. For planner results, count write_files from each story's detail file.

**Build the manifest:**

```json
{
  "slug": "<derived from title, max 40 chars>",
  "scope": {
    "files": <estimated write-target count>,
    "stories": <story count>,
    "complexity": "small | medium | large"
  },
  "route_hint": "standard",
  "prev": "<briefing_path if briefing mode, otherwise null>",
  "skill": "plan-stories",
  "data": {
    "epic_id": "epic-NNN",
    "dev_branch": "dev/<slug>",
    "stories": [
      {
        "id": "story-NNN",
        "title": "<title>",
        "agent": "<agent>",
        "detail_file": "<path>"
      }
    ]
  }
}
```

Write to `.ship-manifest.json` in the project root.

---

## Step 4: Report

Print the manifest path and a summary:

```
Manifest written: .ship-manifest.json
  Epic: <epic_id> — <title>
  Stories: <count> (<complexity>)
  story-NNN: <title> — <agent>
  ...
```

**If invoked standalone** (not from within /ship): prompt the user:
```
Draft plans? (/draft-plans .ship-manifest.json)
```

**If invoked from within /ship**: the orchestrator reads the manifest and proceeds automatically -- no prompt needed.
