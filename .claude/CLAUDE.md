# Orchestration Project

## Session start
When CORRECTION PATTERNS appears at session start:
1. Group entries by theme (same underlying problem)
2. For groups with ≥ 3 entries:
   - **Behavioral** (communication style, judgment calls): auto-promoted to correction_groups DB when count >= 3. Rendered to sidecar at session start.
   - **Process** (workflow steps, tool usage): surface to user — "This keeps happening: [pattern]. Should this become a hook or skill?"
3. Groups with < 3 entries: leave to accumulate — don't act on them yet

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

## Infrastructure internals

### Distilling preferences
Distillation is automated. The stop hook auto-promotes correction patterns (count >= 3) to the correction_groups DB and OpenMemory via om_write.py. At session start, the SessionStart hook renders all promoted/manual preferences from the DB to `.claude/rendered-prefs.md`, which CLAUDE.md @imports for compaction-resilient context injection.

### Tool & model learnings
When a model or tool repeatedly succeeds or fails at a specific task type (2+ occurrences):
1. Store to OpenMemory (procedural sector, global scope) for semantic recall.
These inform model selection (§2) and prompt crafting (§7).

### Integration surfaces
Features that expose registries, hooks, or plugin APIs become implicit dependencies. When shipping one, add or update an `## Integration surfaces` section in that project's CLAUDE.md so future work knows to wire into it. Each entry names the surface, its owner file(s), and the registration pattern.

#### OpenMemory MCP
- **Owner:** registered via `claude mcp add openmemory --scope user`
- **Tools:** openmemory_store, openmemory_query, openmemory_list, openmemory_get, openmemory_reinforce, openmemory_delete
- **Storage:** `~/.claude/.claude/openmemory.sqlite`
- **Scoping:** user_id="global" (cross-project) or user_id="proj:<name>" (per-project)
- **Embeddings:** Ollama nomic-embed-text (local)
