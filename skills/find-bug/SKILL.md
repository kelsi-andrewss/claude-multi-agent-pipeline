---
name: find-bug
description: >
  Find the root cause of a bug using Gemini's large context window. Returns a structured diagnosis
  with most likely location, contributing factors, reproduction steps, and fix direction.
  Use when the user says "/find-bug", "find bug", or "find-bug <symptom>".
  Delegates to the Gemini MCP find_bug tool for large-context root-cause analysis. Supports --model flag.
args:
  - name: args
    type: string
    description: >
      Required symptom description (all text before any flags), and optional --model <id> flag.
---

# Find Bug Skill Invoked

User has requested: `/find-bug {{args}}`

## Steps

### 1. Parse arguments

Parse `{{args}}` into:

- **symptom**: all text before any `--` flag — this is required; if empty, call:
  ```
  AskUserQuestion: "What bug should I investigate?"
  ```
  (free text — no fixed options; wait for the user's response, then use it as `symptom`)
  Do not proceed to Step 2 until a symptom is provided.
- **model**: value after `--model` if present; otherwise `null`

### 2. Load the Gemini find_bug tool

**REQUIRED — do not skip or work around this step.**
Call `ToolSearch` with query `select:mcp__gemini__find_bug` to load the deferred tool.
The tool does not exist in your available tools until this call completes.
Do NOT read files, search code, or attempt any other diagnosis approach.
If `ToolSearch` fails or returns no results: output exactly "Gemini MCP is unavailable." and STOP. Do not proceed to any other step. Do not read files. Do not search code. Do not attempt diagnosis by any other means.

### 3. Call `mcp__gemini__find_bug`

Invoke `mcp__gemini__find_bug` with the parsed parameters:

```
mcp__gemini__find_bug(
  symptom=<symptom string>,
  model=<model string or null>
)
```

Wait for the tool to complete. It will return a structured diagnosis without writing any files.

If the tool returned an error, report it clearly and suggest corrective action (e.g., symptom too vague, no source files found). Stop here if there is an error.

### 4. Choose epic

Call `ToolSearch("mcp__gemini__pm")` then `mcp__gemini__pm_list_epics`.

If epics exist, call `AskUserQuestion` with:
- question: "Which epic should this bug story live in?"
- options: one entry per epic (`<epic_id> — <title>`), plus:
  - label "Create new epic", description "I'll name it after the bug area"
  - label "No epic (backlog)", description "Skip epic assignment"

If the user picks "Create new epic", call a second `AskUserQuestion`:
- question: "What should the new epic be called?"

If no epics exist: use `epic_id = null` and skip the question.

### 6. Launch background agent

Launch one `general-purpose` agent with `run_in_background: true`. Pass it the following prompt (fill in the placeholders):

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

4. Extract the root cause summary (one sentence after "Root cause:") for the story title.

5. Extract from the Gemini diagnosis:
   - write_files: file paths listed under "### Most likely location" and "### Contributing factors"
     (strip line numbers — keep only "path/to/file.ext" format, deduplicated)
   - agent: "architect" if >2 files or fix direction mentions refactor/architecture/redesign; else "quick-fixer"
   - tasks: build from diagnosis sections:
       "Reproduce: <one-line summary from How to confirm>"
       "Fix: <one-line summary from Fix direction>"

6. Call pm_create_story(
     title="Fix: <root cause summary>",
     epic_id=<chosen epic_id or null>,
     write_files=<extracted list>,
     agent=<inferred>,
     tasks=<list above>
   )

7. Call pm_set_plan_file(story_id=<new story id>, plan_file="plans/<name>.md")

8. Return exactly:
   "Done: plans/<name>.md written. Story <story-id> created in <epic-id or backlog>."
```

### 7. Report results

After the background agent completes, print the agent's return string verbatim.
