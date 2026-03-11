# Orchestration Project

## Session start
When CORRECTION PATTERNS appears at session start:
1. Group entries by theme (same underlying problem)
2. For groups with ≥ 3 entries:
   - **Behavioral** (communication style, judgment calls): auto-promote to `behavioral-prefs.md`. Corrections are tracked in `correction_groups` table (epics.db) and auto-promoted by stop hook when count >= 3.
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
Distillation is automated. The stop hook auto-promotes correction patterns (count >= 3) to behavioral-prefs.md and OpenMemory via om_write.py. Auto-distilled entries are prefixed with "(auto-distilled)". Review them at session start to refine wording if needed — but the system works without manual intervention.

### Tool & model learnings
When a model or tool repeatedly succeeds or fails at a specific task type (2+ occurrences):
1. Store to OpenMemory (procedural sector, global scope) for semantic recall.
2. Append a one-liner to `~/.claude/tool-learnings.md` as the audit trail.
If OpenMemory is down, the log entry still captures it.
These inform model selection (§2) and prompt crafting (§7).

### Integration surfaces
Features that expose registries, hooks, or plugin APIs become implicit dependencies. When shipping one, add or update an `## Integration surfaces` section in that project's CLAUDE.md so future work knows to wire into it. Each entry names the surface, its owner file(s), and the registration pattern.

#### OpenMemory MCP
- **Owner:** registered via `claude mcp add openmemory --scope user`
- **Tools:** openmemory_store, openmemory_query, openmemory_list, openmemory_get, openmemory_reinforce, openmemory_delete
- **Storage:** `~/.claude/.claude/openmemory.sqlite`
- **Scoping:** user_id="global" (cross-project) or user_id="proj:<name>" (per-project)
- **Embeddings:** Ollama nomic-embed-text (local)

#### OpenMemory Write Discipline
- **Owner:** `hooks/lib/om_write.py`
- **Rule:** All OpenMemory writes go through om_write(). No direct SQL inserts.
- **Tags:** Only `behavioral-pref`, `tool-learning`, `decision`, `prompt-pattern`, `session-summary`, `critique-learning`, `gemini-blind-spot` accepted.
- **Enforcement:** Tag whitelist, embedding-based dedup (0.85 threshold), per-category budgets, decay-weighted pruning.
- **Ops log:** `~/.claude/.claude/tracking/om-ops.json`

#### Conversation Memory Pipeline
- **Owner:** `hooks/lib/signal_processor.py` (correction-decision correlation)
- **Storage:** `decision_preferences` table in `epics.db`, `correction_groups` table in `epics.db`
- **MCP tools:** `pm_predict_preference` (query predicted preferences for a domain), `pm_decision_insights` (correlate decisions with outcomes)
- **Session hook:** `hooks/load-session-context.sh` outputs `PREDICTED PREFERENCES` section from `decision_preferences` table at session start
- **Write pattern:** `signal_processor.py` correlates corrections with recent decisions and updates `decision_preferences`; stop hook detects corrections in transcript, writes to `correction_groups`, auto-promotes when count >= 3

### Project structure
`~/.claude/` is itself a git project. Claude Code treats `~/.claude/.claude/` as its project-level config folder. That subfolder contains the live infrastructure: `epics.db`, `scripts/epics-cli.sh`, `hooks/`, `prompts/`. Global skills and instructions live at `~/.claude/skills/` and `~/.claude/ORCHESTRATION.md` — duplicating them into `.claude/.claude/skills/` creates drift between two sources of truth.
- Framework-specific patterns (React, Firebase, CSS, Konva) live in `refs/pitfalls-*.md` and are delivered to coders via `pm_list_patterns`.
- Canonical memory files: `memory/*.md` (portable, git-tracked). Run `scripts/setup-memory.sh` on a new machine to symlink into auto memory paths. Run `/bootstrap-memory` to rebuild OpenMemory from flat files.
- When a planning session ends without implementation (plan rejected, approach changed, or pure research), still write a tracking entry — mark it as architecture category and note what was decided against and why.
