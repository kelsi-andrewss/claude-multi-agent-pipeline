# Orchestration Project

## Session start
When CORRECTION PATTERNS appears at session start:
1. Group entries by theme (same underlying problem)
2. For groups with ≥ 3 entries:
   - **Behavioral** (communication style, judgment calls): auto-promote to `behavioral-prefs.md`, then mark entries as `promoted: true` in `correction-tallies.jsonl`
   - **Process** (workflow steps, tool usage): surface to user — "This keeps happening: [pattern]. Should this become a hook or skill?"
3. Groups with < 3 entries: leave to accumulate — don't act on them yet

When UNPROCESSED SESSIONS shows friction clusters, review the session record context to understand what caused rapid-fire user turns.

When you see the SESSION AGENDA, interpret it before waiting for direction:
- If you have a clear recommendation, state it with reasoning (dependency chain, staleness, momentum)
- If you don't have enough context to prioritize, say so — "I see these stories but can't tell why story-340 has been in-progress for 72 hours" is more useful than a guess
- Flag anything that looks wrong (stale stories, blocked-ready with no path forward)
- If nothing is in progress and nothing is ready, say so — don't invent work
- If a SESSION HANDOFF is present, incorporate its context — it contains what the previous session was doing and what needs attention
- If a MEMORY BRIEFING is present, cross-reference it with the agenda per the synthesis protocol in `refs/orch-memory.md`. State predictions with confidence levels before your recommendation. Don't fabricate intuition when the briefing is empty.
This is your "first word" — use it honestly. One paragraph, not a list.

## Main session orchestration rules
See ~/.claude/ORCHESTRATION.md — applies to the main session only, not to spawned agents.
