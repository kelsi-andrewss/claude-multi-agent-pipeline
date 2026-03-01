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

### 4. Report results to user

After the tool completes, print the tool's return string verbatim.
