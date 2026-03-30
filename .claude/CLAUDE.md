# Orchestration Project

## Session start
When CORRECTION PATTERNS appears at session start:
1. Group entries by theme (same underlying problem)
2. For groups with >= 3 entries:
   - **Behavioral** (communication style, judgment calls): auto-promoted to correction_groups DB when count >= 3. Rendered to sidecar at session start.
   - **Process** (workflow steps, tool usage): surface to user — "This keeps happening: [pattern]. Should this become a hook or skill?"
3. Groups with < 3 entries: leave to accumulate — don't act on them yet

When you see the SESSION AGENDA, interpret it before waiting for direction:
- If you have a clear recommendation, state it with reasoning (dependency chain, staleness, momentum)
- If you don't have enough context to prioritize, say so honestly
- Flag anything that looks wrong (stale stories, blocked-ready with no path forward)
- If nothing is in progress and nothing is ready, say so — don't invent work
- If a SESSION HANDOFF is present, incorporate its context
- If a MEMORY BRIEFING is present, cross-reference it with the agenda per `refs/orch-memory.md`
This is your "first word" — use it honestly. One paragraph, not a list.

## Main session orchestration rules
See ~/.claude/ORCHESTRATION.md — applies to the main session only, not to spawned agents.
