# Orchestration Project

## Session start
When UNPROCESSED SESSIONS shows AUTO: corrections, verify them before starting new work: read the `corrections.md` entries, confirm or correct them, and mark as verified by removing the `AUTO:` prefix. Delete false positives.

When the session context shows MEMORY QUEUE: DRAIN REQUIRED, drain it as your first action:
1. Read memory-queue.md
2. Deduplicate entries (same content → store once)
3. Call openmemory_store for each unique entry
4. Overwrite memory-queue.md with just the header (clearing it)

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
