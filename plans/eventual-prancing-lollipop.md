# Plan: gemini-audit Skill

## Context

The existing `/audit` skill uses a general-purpose Claude subagent to read files and produce a report.
We want a new `/gemini-audit` skill that delegates the heavy lifting to the **Gemini MCP server's `audit` tool** instead, so Gemini's large context window does the file reading and analysis directly — no intermediate agent needed.

## Skill: `gemini-audit`

**Location:** `~/.claude/skills/gemini-audit/SKILL.md`

### Argument surface

Same as `/audit` but simpler — only the flags the Gemini `audit` tool actually supports:

| Arg token | Maps to |
|-----------|---------|
| bare paths | `paths` list |
| `security`, `bugs`, `completeness`, `quality` | `sections` list |
| `--summary` | `summary_only: true` |
| `--ignore <glob>` | `ignore_patterns` list |
| `--model <id>` | `model` override |

### Steps in the SKILL.md

1. **Parse `{{args}}`** into paths, sections, summary_only, ignore_patterns, model override.
2. **Load the `mcp__gemini__audit` tool** via `ToolSearch` (required before calling deferred tools).
3. **Call `mcp__gemini__audit`** with the parsed parameters.
4. **Report output path** (`AUDIT-GEMINI.md` at project root) and findings summary to user.

### SKILL.md trigger description

```
Use when the user says "/gemini-audit", "gemini audit the codebase", or "gemini audit <path>".
Delegates to the Gemini MCP audit tool for large-context analysis.
```

## Critical files

| File | Action |
|------|--------|
| `~/.claude/skills/gemini-audit/SKILL.md` | **Create** (new skill) |
| `~/.claude/mcp-servers/gemini/server.py` | Read-only reference — `audit()` tool at lines 491–575 |
| `~/.claude/skills/audit/SKILL.md` | Read-only reference for format |

## Verification

1. Run `/gemini-audit` with no args → `mcp__gemini__audit` called with `paths=null`; `AUDIT-GEMINI.md` written to project root.
2. Run `/gemini-audit security flutter/` → `sections=["security"]`, `paths=["flutter/"]` passed through.
3. Run `/gemini-audit --summary` → `summary_only=true` passed; output is executive summary only.
4. Check `~/.claude/skills/gemini-audit/SKILL.md` exists and Claude Code lists it as an available skill.
