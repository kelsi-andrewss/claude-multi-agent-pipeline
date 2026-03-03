---
name: argue
description: >
  Adversarial Claude-vs-Gemini debate tool. Runs a back-and-forth loop where Claude and Gemini
  challenge each other until convergence is confirmed or the round cap is hit. Produces a
  battle-tested synthesis written to ~/.claude/arguments/finals/<slug>.md.
  Use when the user says "/argue <topic>", "/argue plan <topic>", "/argue bug <symptom>",
  or "/argue tech <question>".
args:
  - name: args
    type: string
    description: >
      Topic and optional flags: --rounds N, --paths file1,file2, --seed find_bug|plan|audit,
      --model <id>, --history.
---

# Argue Skill Invoked

User has requested: `/argue {{args}}`

## Steps

### 1. Parse arguments

Parse `{{args}}` into:

- **topic_type**: if args starts with `plan `, `bug `, or `tech `, extract it and strip from topic. Default: `general`.
- **topic**: all text before any `--` flag (after stripping topic_type prefix). Required. If empty, call:
  ```
  AskUserQuestion: "What should Claude and Gemini debate?"
  ```
  Wait for the user's response before proceeding.
- **max_rounds**: value after `--rounds` (integer, 1–8). Default: 4.
- **context_paths**: comma-separated file paths after `--paths`. Split into a list.
- **seed_tool**: value after `--seed` (`find_bug`, `plan`, or `audit`). Default: null.
- **model**: value after `--model`. Default: null.
- **history_flag**: true if `--history` appears in args.

### 2. Load the argue tool

**REQUIRED — do not skip.**
Call `ToolSearch` with query `select:mcp__gemini__argue` to load the deferred tool.
If ToolSearch fails or returns no results: output exactly "Gemini MCP is unavailable." and STOP.

### 3. Run the debate

Call `mcp__gemini__argue` with parsed parameters:

```
mcp__gemini__argue(
  topic=<topic>,
  topic_type=<topic_type>,
  context_paths=<list or null>,
  context_docs=null,
  seed_tool=<seed_tool or null>,
  seed_tool_args=null,
  max_rounds=<max_rounds>,
  model=<model or null>
)
```

This is a single call. Wait for it to return — it runs the full debate loop internally.

If it returns a JSON object with an `"error"` key, report the error clearly and STOP.

### 4. Parse result

Parse the returned JSON. Extract:
- `converged` (bool)
- `tension_summary` (string)
- `rounds_run` (int)
- `messages` (list of {role, content})
- `skipped_paths` (list, may be absent)

### 5. Synthesize

Read `messages` and write a final synthesis:

- If `converged == true`:
  > **Agreed position:** <1–3 sentence summary of the convergent position>

- If `converged == false`:
  > **Positions not fully reconciled after <rounds_run> round(s).**
  > **Key tension:** <tension_summary>
  > **Best available synthesis:** <Claude's own reasoned synthesis of the strongest points from both sides>

### 6. Save outputs

**Slug**: topic lowercased, spaces → hyphens, non-alphanumeric stripped, truncated to 40 chars.

**Finals file** (always written):
- Path: `~/.claude/arguments/finals/<slug>.md`
- Content:
  ```
  # Argue: <topic>
  **Type**: <topic_type>  **Rounds**: <rounds_run>  **Converged**: <yes/no>
  **Date**: <YYYY-MM-DD>

  ## Synthesis

  <synthesis text>

  ## Tension summary

  <tension_summary>
  ```
- Overwrite if it already exists.

**History file** (only if `--history` flag was set):
- Path: `~/.claude/arguments/history/<slug>-<topic_type>-<YYYYMMDDTHHMMSS>.md`
- Content: full transcript — each message formatted as `**<ROLE>**: <content>`, separated by `---`.
- After writing, list all files in `~/.claude/arguments/history/` matching `<slug>-*`, sort by mtime descending, delete any beyond the 5 most recent.

**Plan handoff** (only if `topic_type == "plan"`):
- Write the synthesis to `plans/<whimsical-adjective-gerund-noun>.md` (check existing plans/ to avoid collision).
- Then ask:
  > "Argument complete. Run `/draft-plan` to wire this into a story, or keep as standalone?"
- If the user says yes: invoke `/draft-plan` pointing at the plan file.

### 7. Report

Print the synthesis inline. Note:
- Path written to finals
- Path written to history (if --history)
- Any skipped_paths from the result
