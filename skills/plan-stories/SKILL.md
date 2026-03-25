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

3. **Inline mode**: everything else. Parse for single-category or multi-category input:

   **Multi-category detection**: If args contain semicolons separating category-labeled groups (e.g., `"Hooks: 1. foo 2. bar; Skills: 1. baz 2. qux"`), parse into `epics_input` -- a list where each entry has `category` (the label before the colon) and `items` (the numbered items after). Derive `title` per entry from the category label.

   **Single-category** (no semicolons or no category labels): Extract as before:
   - Quoted string or text before numbered items -- `title`
   - Remaining numbered or comma-separated items -- `items` list
   - Wrap into a 1-element `epics_input` list: `[{category: null, title: <title>, items: <items>}]`

   Resume mode and briefing/file mode also produce a 1-element `epics_input` list with `category: null`.

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
   - Wrap into `epics_result`: `[{epic_id: null, dev_branch: null, stories: <stories>}]`

   **Full path (>2 write targets):**
   - `pm_create_epic(title=<title>)` -- use returned `epic_id`
   - Agent: parsed `Agent:` line, or `architect`
   - `pm_create_story(title=<title>, epic_id=<epic_id>, agent=<agent>, write_files=<write targets>)`
   - `pm_update_story(story_id=<new id>, plan_file="<plan file path>")`
   - Set `stories` = single-element list with the created story
   - Derive `dev_branch` from epic metadata
   - Wrap into `epics_result`: `[{epic_id: <epic_id>, dev_branch: <dev_branch>, stories: <stories>}]`

4. Skip to Step 3.

---

## Step 2: Dispatch planner agent (foreground)

**Run for briefing mode, inline mode, and resume mode.**

### Flow trace (pre-decomposition)

Before dispatching the planner agent, if `items` count >= 3: write a DATA_FLOW_TRACE to include as planner prompt context. The trace is a linear sequence of data transformations from user action to final state.

Format: `[user action] → [data A at location X] → [transform B] → [data C at location Y] → ... → [final state]`

Every story must own a contiguous segment of this chain. Boundary formats between stories must be explicit (what data, what format, where). Include the trace in the planner prompt as a `DATA_FLOW_TRACE:` block after the items list.

If `items` count < 3, skip this substep — the decomposition is simple enough that seam risks are low.

### Planner dispatch

Launch the **planner** agent in foreground with the parsed inputs:

**For briefing mode and inline mode:**

```
Agent(subagent_type="planner", prompt="""
MODE: ship
TITLE: <title>
ITEMS: <items list>
CONTEXT: <briefing_contents if briefing mode, otherwise omit>

DECOMPOSITION RULE: Minimize write-target file overlap across stories. Group changes by the files they modify, not by conceptual theme or tier. A story that owns a file implements ALL changes to that file across all features in the epic. If two stories would share a write-target file, restructure them to eliminate the overlap — every shared file serializes those stories and kills parallelism. Decomposition priority: file ownership > conceptual grouping. DATA_FLOW_TRACE: Before decomposing into stories, write the end-to-end data transformation chain as a linear sequence. Format: `[step] → [step] → ...` with explicit data format at each boundary. Every story must own a contiguous segment. If story N produces data consumed by story M, the boundary must specify: what data, what format, what location. Include this trace in each story's description so the plan-writer can verify seam correctness.

UI CODEGEN TAGGING: For each story, determine if it involves UI component creation or modification.
Set `ui_codegen: true` AND `agent: ui-coder` on stories where the primary work is visual/layout
(new components, redesigns, UI-heavy features, screens, pages, widgets, dashboards, forms with
custom layouts). The ui-coder agent MUST use Gemini's gemini_ui_code tool for ALL visual component
code — it never writes markup/styles itself. Set `ui_codegen: false` for backend, data,
infrastructure, or stories where UI is incidental (e.g., adding a field to an existing form).
IMPORTANT: quick-fixer and architect agents CANNOT generate UI code via Gemini. If a story has
visual components, it MUST be tagged ui_codegen: true with agent: ui-coder.

TEST_FILES RULE: For each story that creates or modifies functional code (logic, state transitions, data transforms, API handlers, business rules), set `test_files` to the corresponding test file paths using the project's convention (test_<file>.py, <file>.test.ts, <file>_test.dart, etc.). Stories that are pure docs, config (YAML/JSON/env), scaffold/boilerplate (project init, dependency install), or pure refactors that don't change observable behavior should set `needs_testing: false` instead. When in doubt, set test_files — the merge gate catches real bugs, skipping it hides them.

BEHAVIORAL_ACCEPTANCE_CRITERIA RULE: For any story that creates UI components, connects endpoints, or wires event handlers, acceptance criteria MUST be behavioral flows — "user does X → Y happens" — not structural assertions ("component exists", "file created"). Each flow criterion traces the full chain: user action → event handler → state change → UI update. Structural criteria are acceptable only for pure backend/infrastructure stories with no user-facing interaction.
""")
```

**For resume mode:**

```
Agent(subagent_type="planner", prompt="""
MODE: ship
EPIC_ID: epic-NNN

DECOMPOSITION RULE: Minimize write-target file overlap across stories. Group changes by the files they modify, not by conceptual theme or tier. A story that owns a file implements ALL changes to that file across all features in the epic. If two stories would share a write-target file, restructure them to eliminate the overlap — every shared file serializes those stories and kills parallelism. Decomposition priority: file ownership > conceptual grouping. DATA_FLOW_TRACE: Before decomposing into stories, write the end-to-end data transformation chain as a linear sequence. Format: `[step] → [step] → ...` with explicit data format at each boundary. Every story must own a contiguous segment. If story N produces data consumed by story M, the boundary must specify: what data, what format, what location. Include this trace in each story's description so the plan-writer can verify seam correctness.

UI CODEGEN TAGGING: For each story, determine if it involves UI component creation or modification.
Set `ui_codegen: true` AND `agent: ui-coder` on stories where the primary work is visual/layout
(new components, redesigns, UI-heavy features, screens, pages, widgets, dashboards, forms with
custom layouts). The ui-coder agent MUST use Gemini's gemini_ui_code tool for ALL visual component
code — it never writes markup/styles itself. Set `ui_codegen: false` for backend, data,
infrastructure, or stories where UI is incidental (e.g., adding a field to an existing form).
IMPORTANT: quick-fixer and architect agents CANNOT generate UI code via Gemini. If a story has
visual components, it MUST be tagged ui_codegen: true with agent: ui-coder.

TEST_FILES RULE: For each story that creates or modifies functional code (logic, state transitions, data transforms, API handlers, business rules), set `test_files` to the corresponding test file paths using the project's convention (test_<file>.py, <file>.test.ts, <file>_test.dart, etc.). Stories that are pure docs, config (YAML/JSON/env), scaffold/boilerplate (project init, dependency install), or pure refactors that don't change observable behavior should set `needs_testing: false` instead. When in doubt, set test_files — the merge gate catches real bugs, skipping it hides them.

BEHAVIORAL_ACCEPTANCE_CRITERIA RULE: For any story that creates UI components, connects endpoints, or wires event handlers, acceptance criteria MUST be behavioral flows — "user does X → Y happens" — not structural assertions ("component exists", "file created"). Each flow criterion traces the full chain: user action → event handler → state change → UI update. Structural criteria are acceptable only for pure backend/infrastructure stories with no user-facing interaction.
""")
```

**Multi-epic dispatch**: When `epics_input` has multiple entries, launch ALL planner agents in parallel as **background agents** (`run_in_background: true`) — one per entry, all in a single message. Each epic is independent (no cross-epic dependencies at planning time), so there's no reason to serialize. Wait for all to complete, then collect results into `epics_result`: `[{epic_id, dev_branch, stories}]`. Single-entry `epics_input` uses a single foreground agent (unchanged).

**On PLANNER_RESULT**: Extract `epic_id`, `dev_branch`, and the story list (IDs, titles, agents, detail_file paths) per epic. Wrap into `epics_result` array. Proceed to Step 3.

**On PLANNER_ERROR**: Surface the error to the user with full details (step, tool, error message, partial results). Do NOT fall back to direct MCP calls -- the failure causes (MCP down, Gemini garbage, agent context limit) would also fail here. Do NOT write a manifest. Let the user decide: retry, adjust input, or abort. Stop.

---

## Step 3: Write .ship-manifest.json

Build the manifest from `epics_result` collected in Step 1 (execute mode) or Step 2 (planner result). `epics_result` is always an array -- even single-epic flows use a 1-element array.

**Derive slug**: For single-epic manifests, derive from the epic title. For multi-epic manifests, derive from the first epic's title (or a combined slug if titles share a common prefix). Lowercase, hyphen-separated, max 40 chars.

**Scope aggregation** (sums across all epics):
- `stories`: total story count across all entries in `epics_result`
- `files`: sum of write-target counts across all stories in all epics
- `complexity`: uses total story count -- small = 1 story, medium = 2-4 stories, large = 5+ stories

**Build the manifest:**

```json
{
  "slug": "<derived, max 40 chars>",
  "scope": {
    "files": <total write-target count across all epics>,
    "stories": <total story count across all epics>,
    "complexity": "small | medium | large"
  },
  "route_hint": "standard",
  "prev": "<briefing_path if briefing mode, otherwise null>",
  "skill": "plan-stories",
  "data": {
    "epics": [
      {
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
    ]
  }
}
```

> **Backward compatibility**: Consumers should check for `data.epics` first. If absent (old manifest written before this change), read `data.epic_id` + `data.stories` and wrap into a 1-element epics array: `[{epic_id: data.epic_id, dev_branch: data.dev_branch, stories: data.stories}]`.

Write to `.ship-manifest.json` in the project root.

---

## Step 4: Report

**If invoked standalone** (not from within /ship): print the manifest summary and prompt. Iterate through `data.epics` to list each epic and its stories:

```
Manifest written: .ship-manifest.json
  Epic: <epic_id> — <title> (dev/<slug>)
    story-NNN: <title> — <agent>
    ...
  Epic: <epic_id> — <title> (dev/<slug>)
    story-NNN: <title> — <agent>
    ...
  Total: <count> stories (<complexity>)

Draft plans? (/draft-plans .ship-manifest.json)
```

Single-epic flows show the same layout (one epic block).

**If invoked from within /ship**: do not print a summary or prompt. The manifest is a machine-readable artifact — the orchestrator reads it and proceeds automatically. Any output here causes a false pause.
