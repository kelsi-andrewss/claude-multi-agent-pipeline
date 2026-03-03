---
name: gemini-audit
description: >
  Audit a codebase using Gemini's large context window and write a structured AUDIT-GEMINI.md report.
  Use when the user says "/gemini-audit", "gemini audit the codebase", or "gemini audit <path>".
  Delegates to the Gemini MCP audit tool for large-context analysis. Supports scoping to files or
  directories, section filters (security, bugs, completeness, quality), --summary, --ignore, and
  --model flags.
args:
  - name: args
    type: string
    description: >
      Optional. Any combination of: paths, section keywords (security|bugs|completeness|quality),
      and flags (--summary, --ignore <glob>, --model <id>).
---

# Gemini Audit Skill Invoked

User has requested: `/gemini-audit {{args}}`

## Steps

### 1. Parse arguments

- **paths**: non-flag, non-section tokens
- **sections**: `security`, `bugs`, `completeness`, `quality` — all matches; `null` if none
- **summary_only**: `true` if `--summary`; else `false`
- **ignore_patterns**: values after each `--ignore`; `null` if none
- **model**: value after `--model`; else `null`

### 2. Load the Gemini audit tool

Call `ToolSearch` with query `select:mcp__gemini__audit` to load the deferred tool before use.
This step is **required** — the tool is not available until loaded.

### 3. Call `mcp__gemini__audit`

Invoke `mcp__gemini__audit` with the parsed parameters:

```
mcp__gemini__audit(
  paths=<paths list or null>,
  sections=<sections list or null>,
  summary_only=<true|false>,
  ignore_patterns=<ignore_patterns list or null>,
  model=<model string or null>
)
```

Wait for the tool to complete. It will write `AUDIT-GEMINI.md` to the project root and return the report content.

### 4. Cross-reference findings against open stories

Call `pm_list_stories()` (no filters — defaults to non-archived). From the returned JSON array, filter to stories where `state` is not `done`, `shipped`, or `archived`.

Build a map:
```
open_story_map = { story_id: { title, writeFiles[] } }
```
Parse each story's `write_files` as a JSON array.

Read the written report at `AUDIT-GEMINI.md` in the project root.

For each finding in the report that references a specific file path:
- Check open_story_map for any story whose `writeFiles` array contains a path that matches or overlaps the finding's referenced file.
- If a match is found, append to that finding's section in the report:
  ```
  Related open story: story-NNN — <title>
  ```

If any annotations were added, write the updated report back to `AUDIT-GEMINI.md`.

### 5. Offer story creation for uncovered High priority findings

Scan the report for findings marked as priority `High` that do NOT have a "Related open story" annotation (i.e., not already covered by an open story).

If any such findings exist, list them to the user and ask:
> "The following High priority findings are not covered by any open story. Create a /todo story for each? (yes / no / list the ones you want)"

If the user says yes (or selects specific items), invoke `/todo` for each selected finding using the finding's title and description as the task description.

### 6. Print completion summary

Output the following to the user:

```
Audit complete.
Report: AUDIT-GEMINI.md
Findings: <N> High, <N> Medium, <N> Low
<if stories created>: Stories created: story-NNN, ...
```
