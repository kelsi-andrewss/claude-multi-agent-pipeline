# Plan: /find-bug Skill

## Context

No dedicated bug-finding skill exists. The Gemini MCP server has a `find_bug` tool that performs root-cause analysis using Gemini's large context window — it auto-discovers source files, reads up to 200KB of code, and returns a structured diagnosis without writing any files. This skill wraps that tool the same way `/gemini-audit` wraps `mcp__gemini__audit`.

The goal: a `/find-bug <symptom>` command that delegates analysis entirely to Gemini, keeping file reads out of the main Claude context window.

---

## Implementation

**New file:** `/Users/kelsiandrews/.claude/skills/find-bug/SKILL.md`

Model it directly on `/Users/kelsiandrews/.claude/skills/gemini-audit/SKILL.md`:

1. **Parse args** — `symptom` (all text before any flags, required) and optional `--model <id>`
2. **Load tool** — `ToolSearch` with `select:mcp__gemini__find_bug`
3. **Invoke** — `mcp__gemini__find_bug(symptom=..., model=...)`
4. **Report** — print Gemini's structured output directly to the user

**Gemini output format** (enforced by server.py system instruction):
```
Root cause: one-sentence summary

### Most likely location
- `path/to/file:line` — explanation

### Contributing factors
- related code paths

### How to confirm
- reproduction steps / failing assertion

### Fix direction
- high-level fix description (no code)
```

**Register the skill** — add trigger line to the skill description so it appears in the `system-reminder` skill list (same pattern as gemini-audit).

---

## Critical Files

| File | Action |
|------|--------|
| `/Users/kelsiandrews/.claude/skills/find-bug/SKILL.md` | **Create** |
| `/Users/kelsiandrews/.claude/skills/gemini-audit/SKILL.md` | Reference only (copy structure) |
| `/Users/kelsiandrews/.claude/mcp-servers/gemini/server.py` | Reference only (`find_bug` at lines 728–767) |
| `/Users/kelsiandrews/.claude/settings.json` | Check if skills need explicit registration |

---

## Verification

1. In a project directory, run `/find-bug the login button freezes when clicked twice`
2. Confirm `ToolSearch` loads `mcp__gemini__find_bug` without error
3. Confirm Gemini's structured output (Root cause / Most likely location / etc.) is printed
4. Run `/find-bug <symptom> --model gemini-2.0-flash` to verify model override works
5. Confirm no files are read by Claude itself (Gemini handles all file discovery internally)
