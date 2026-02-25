---
name: audit
description: >
  Audit a codebase and write a structured AUDIT.md report via a foreground Opus agent.
  Use when the user says "/audit", "audit the codebase", "audit story-NNN", or "audit <path>".
  Supports scoping to files, directories, story diffs, or time ranges. Supports section
  filters (security, bugs, completeness, quality), --requirements, --output, --append,
  --ignore, --summary, --json, --no-completeness, and --since flags.
args:
  - name: args
    type: string
    description: >
      Optional. Any combination of: paths, story-NNN, section keywords
      (security|bugs|completeness|quality), and flags
      (--requirements <path>, --output <path>, --append, --ignore <glob>,
      --summary, --json, --no-completeness, --since <commit|date>).
---

# Audit Skill Invoked

User has requested: `/audit {{args}}`

## Steps

### 1. Parse arguments

Parse `{{args}}` into the following categories:

- **paths**: any token that is not a flag and not `story-NNN` and not a section keyword — collect as target paths
- **story_id**: token matching `story-\d+` — at most one
- **section_filter**: token matching one of: `security`, `bugs`, `completeness`, `quality` — at most one (collect all that match; if multiple given, run all of them)
- **flag_requirements**: value after `--requirements` if present
- **flag_output**: value after `--output` if present
- **flag_append**: present if `--append` appears
- **flag_ignore**: all values after each `--ignore` occurrence (collect list)
- **flag_summary**: present if `--summary` appears
- **flag_json**: present if `--json` appears
- **flag_no_completeness**: present if `--no-completeness` appears
- **flag_since**: value after `--since` if present

If none of paths, story_id, or flag_since are provided → full project audit mode.

### 2. Resolve the project root

Identify the project root as the directory containing the nearest `.git` folder walking up from the current working directory. Store as `<project-root>`.

### 3. Resolve target file list

Exactly one of the following applies (in priority order):

**A. story_id is set:**
- Read `.claude/epics.json` from the project root.
- Find the story entry whose `id` matches story_id. Extract its `branch` field.
- If branch is null or not found, stop and report: "story_id not found in epics.json or has no branch."
- Run: `git -C <project-root> diff main...story/<branch> --name-only`
- Collect the output lines as the target file list.
- If the list is empty, report: "No files changed in story/<branch> vs main." and stop.

**B. flag_since is set:**
- Run: `git -C <project-root> log --since="<flag_since>" --name-only --pretty=format:"" | sort -u`
- Collect non-empty output lines as the target file list.
- If empty, report: "No files changed since <flag_since>." and stop.

**C. paths are set:**
- Use the provided paths as-is as the target scope description.

**D. No scope given:**
- Target scope is the full project root.

Apply ignore filters: for each glob in flag_ignore, exclude matching paths from the target list.

### 4. Auto-discover requirements document

In order:
1. If flag_requirements is set → use that path. If file does not exist, stop and report.
2. Else check for `<project-root>/REQUIREMENTS.md` → use if exists.
3. Else check for `<project-root>/requirements.pdf` → use if exists.
4. Else → set requirements_path to null and note: "No requirements document found — completeness section will be skipped."

If flag_no_completeness is set, override to null regardless.

### 5. Load epics.json for cross-reference

Read `.claude/epics.json`. Build a map:
```
open_story_map = { story_id: { title, writeFiles[] } }
```
Include only stories where `state` is NOT `closed`. This is used in step 8.

### 6. Build the audit prompt

Start with the base text from `~/.claude/AUDIT-PROMPT.md` (read that file verbatim).

Append the following sections as relevant:

**Scope section** (always):
```
## Audit Scope
<one of the following>
- Full project: <project-root>
- Target files/directories: <comma-separated list>
- Story diff (story/<branch> vs main): <file list>
- Files changed since <flag_since>: <file list>

Ignored patterns: <flag_ignore list, or "none">
```

**Requirements section** (if requirements_path is not null):
```
## Requirements Document
Path: <requirements_path>
Read this file as the source of truth for the Completeness section.
```

**Section filter** (if section_filter is set):
```
## Section Filter
Only produce the following section(s) of the report: <section_filter list>.
Omit all other sections from the output.
```

**Output format** (if flag_summary or flag_json):
```
## Output Format
<if flag_summary>: Produce an executive summary only — skip detailed per-finding sections.
<if flag_json>: Output the report as a JSON object with keys: summary, completeness, quality, bugs, recommendations, score. No markdown prose.
```

**Append mode** (if flag_append):
```
## Append Mode
An existing report may already exist at <output_path>. Read it first, then append new findings
as additional sections rather than rewriting the full report. Do not duplicate findings already
present.
```

**Output instruction** (always, last):
```
## Output
Write the complete report to: <output_path>
```

### 7. Determine output path

- If flag_output is set → use that as output_path.
- Else → output_path = `<project-root>/AUDIT.md`

### 8. Launch the Opus agent (foreground)

Launch a **general-purpose** subagent with model `opus` in **foreground** (not background) using the composed prompt from step 6.

The agent's job is to:
- Read all target files
- Read the requirements document if provided
- Produce the full audit report
- Write the report to output_path

Wait for the agent to complete before proceeding.

### 9. Cross-reference findings against open stories

After the agent completes, read the written report at output_path.

For each finding in the report that references a specific file path:
- Check open_story_map (from step 5) for any story whose `writeFiles` array contains a path that matches or overlaps the finding's referenced file.
- If a match is found, append to that finding's section in the report:
  ```
  Related open story: story-NNN — <title>
  ```

If any annotations were added, write the updated report back to output_path.

### 10. Offer story creation for uncovered High priority findings

Scan the report for findings marked as priority `High` that do NOT have a "Related open story" annotation (i.e., not already covered by an open story).

If any such findings exist, list them to the user and ask:
> "The following High priority findings are not covered by any open story. Create a /todo story for each? (yes / no / list the ones you want)"

If the user says yes (or selects specific items), invoke `/todo` for each selected finding using the finding's title and description as the task description.

### 11. Print completion summary

Output the following to the user:

```
Audit complete.
Report: <output_path>
Findings: <N> High, <N> Medium, <N> Low
<if stories created>: Stories created: story-NNN, ...
```
