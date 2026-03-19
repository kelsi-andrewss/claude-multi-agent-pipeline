# Memory Pipeline Self-Learning Refactor

## Problem Statement
**What problem?** The memory pipeline records user corrections and displays them in session context, but three feedback channels are broken: decision-outcome correlation (Stage 2 — table never created), enforcement hook generation (Stage 5 — output directory missing), and decision score rendering (never implemented). The system is self-documenting but not self-learning — behavioral conditioning relies entirely on the LLM reading a text file, with no structural enforcement or statistical bias.

**Why fix it?** Corrections repeat across sessions because there's no mechanism to actually change behavior beyond prompt injection. The "correction detected 51x" entry in rendered-prefs.md is evidence: the system recorded the pattern repeatedly but couldn't prevent recurrence. Without closing the loop, the infrastructure is complexity without payoff.

**Why integral?** This is the orchestration project's core differentiator. Research confirms no coding assistant (Cursor, Copilot, Windsurf, Claude Code) does dynamic behavioral learning from corrections. Our pipeline already exceeds industry standard for the working parts — fixing the broken parts puts us genuinely ahead. The infrastructure was designed for this; the code exists but was never activated.

**End goal:** A correction that reaches promotion threshold produces three conditioning effects: (1) text in rendered-prefs.md (already works), (2) a warn-only compliance hook that fires before the bad pattern repeats (Stage 5 fix), and (3) a negative signal_score on the associated decision that's visible in session context (Stage 2 fix + rendering). Observable outcome: the next session sees the preference text AND the decision penalty, and structural hooks intercept hookable mistakes before they happen.

## Overview
This refactor closes the feedback loop in the memory/self-learning pipeline. The five-stage background processor (stop_processor.py) has three working stages and two broken ones — not because of design flaws, but because prerequisites were never created (one database table, one filesystem directory). The existing code for Stage 2 (decision-outcome correlation) and Stage 5 (hook generation) is already written, tested (Stage 5 has 16 inline tests), and architecturally sound. The refactor creates the missing prerequisites, wires in dead code for semantic correction grouping, renders decision scores into session context, and cleans up data quality issues.

## Summary
Refactor the memory/self-learning pipeline to close three broken feedback channels. Stage 2 (decision-outcome correlation via signal_score in decision_preferences) and Stage 5 (compliance hook generation) are already coded but their prerequisites don't exist — create the decision_preferences table in epics.db and ensure the compliance/ directory exists. Wire in the existing _find_matching_group() for semantic correction grouping (replacing exact text match). Add decision score rendering to load-session-context.sh so negatively-scored decisions appear in session context. Clean up inflated correction counts, dead settings.json hook references, and inaccurate CLAUDE.md documentation. Research validates: our architecture aligns with Letta/LangMem patterns, our count-based promotion is more structured than LLM-driven alternatives, and no production system has closed-loop decision conditioning — making our approach novel.

## Features

### MVP
1. **Create decision_preferences table** — Add schema migration to load-session-context.sh that creates the table (matching tools_pm_decisions.py schema: id, decision_type, context, chosen_path, alternatives, session_id, confidence, signal_score, signal_count, created_at, updated_at). This unblocks Stage 2 of stop_processor.py.
   - Target: `hooks/load-session-context.sh` (migration block)
   - Read: `mcp-servers/gemini/tools_pm_decisions.py` (canonical schema)

2. **Fix Stage 5 hook generation** — Ensure `hooks/compliance/` directory exists before hook_generator.py attempts to write. Clean dead hook references from settings.json. Stage 5 code is already correct — just needs its output directory.
   - Target: `hooks/lib/stop_processor.py` (mkdir before Stage 5 call)
   - Target: `settings.json` (remove dead compliance hook entries)

3. **Wire semantic correction grouping** — Replace exact text match (WHERE theme = ?) in process_session_corrections() with the existing _find_matching_group() embedding-based similarity lookup. This deduplicates the 48 accumulating entries that are semantically identical but textually different.
   - Target: `hooks/lib/signal_processor.py` (wire _find_matching_group into process_session_corrections)
   - Constraint: decision-43, decision-75 — all detection stays in signal_processor.py, process_session_corrections() remains the entry point

4. **Render decision scores in session context** — Add a section to load-session-context.sh that queries decision_preferences for negatively-scored decisions (signal_score < 0) and appends them to rendered-prefs.md under a "Decision Health" heading.
   - Target: `hooks/load-session-context.sh` (new rendering block after prefs block)

5. **Data cleanup and documentation accuracy** — Fix inflated correction_group counts from pre-rate-limit era. Update CLAUDE.md to accurately reflect decision_preferences status. Clean stale correction_groups entries where count was inflated from a single session.
   - Target: `CLAUDE.md` (behavioral learning section)
   - Target: `hooks/load-session-context.sh` (one-time data cleanup migration)

### Phase 2 (defer)
6. **Context-aware preference filtering** — When preference count exceeds ~20, filter rendered-prefs.md by relevance to current task context (project-scoped, keyword-matched). Research (CIPHER k-nearest-context) shows this outperforms monolithic injection, but at 7 prefs the token cost doesn't justify it.

7. **Temporal preference supersession** — Add valid_at/invalid_at timestamps to correction_groups (Zep/Graphiti pattern). New corrections automatically supersede conflicting old ones. Low priority at current scale — manual dismissal suffices.

### Cut
8. **LLM observer/generalizer pass** — CIPHER-style LLM pass that generalizes raw corrections into context-aware behavioral rules. High complexity, uncertain value — our threshold-based promotion with human-readable rendered text already works. Reconsider after measuring whether the current three-channel approach reduces correction recurrence.

## Technical Research

### Architecture
The five-stage background pipeline (stop_processor.py) is architecturally aligned with Letta's Sleep-time Compute and LangMem's Reflect-Reconcile-Update patterns — background post-session consolidation is the established approach. The refactor keeps this architecture intact and activates the two dormant stages.

Three-channel behavioral conditioning (text + hooks + decision scoring) has no direct precedent in production systems. Research confirms: prompt injection + structural guardrails IS the state of the art for inference-time conditioning. Decision scoring adds a statistical layer that no published system implements end-to-end.

### Key Research Findings Informing Decisions
- **Letta/LangMem**: Use LLM-driven memory promotion. Our count-based threshold (>= 3) is simpler but more predictable and doesn't require an extra LLM call. Keep ours.
- **CIPHER**: Context-aware preference retrieval outperforms monolithic rules. Deferred — not needed at 7 preferences.
- **Decision-outcome correlation**: Nascent field (formalized 2025, best accuracy 52% at CHIEF). Our text overlap + temporal proximity approach is pragmatically appropriate for a single-user system. The issue is infrastructure (missing table), not algorithmic.
- **Hook auto-generation**: No published system does this. Our hook_generator.py is novel. Warn-only mode is the right starting point.
- **Coding assistants**: All major tools use static rules files. Our correction-to-preference pipeline already exceeds the industry standard.

### Patterns
- **Correction detection**: All in signal_processor.py (decision-43). process_session_corrections() is the single entry point (decision-75).
- **Persistence**: Three surfaces only (decision-79): correction_groups table, rendered-prefs.md, openmemory.sqlite. Do not add new surfaces.
- **Error handling**: Silent failure in background pipeline — log to /tmp/stop-processor-{session}.log, never crash the session. Session-start hook has 10s timeout — Python subprocesses must complete quickly.
- **Database access**: Claude writes plan_file and state via pm_update_story. Schema migrations in load-session-context.sh. No raw INSERT/UPDATE except through established paths.
- **Embeddings**: Ollama nomic-embed-text at localhost:11434. Graceful degradation when unavailable — correction detection returns empty, dedup falls back to MD5 simhash.

### Dependencies
- `sqlite3` — epics.db, run-state.db
- `Ollama` (nomic-embed-text) — embeddings for correction detection, dedup, OpenMemory
- `hooks/lib/embedding_utils.py` — shared embedding interface
- `hooks/lib/om_write.py` — OpenMemory write gate (7 tags, per-category budgets)

### Gotchas
- **Inflated correction counts**: 48 accumulating entries have counts inflated from pre-rate-limit era. Some show count=78 from a single session date. Data cleanup migration needed.
- **Dead settings.json references**: Two compliance hook paths in settings.json reference non-existent files. Must be cleaned to avoid confusion.
- **CLAUDE.md inaccuracy**: References decision_preferences table as active infrastructure — it doesn't exist yet. Must be updated post-migration.
- **SQLite contention**: Background stop_processor and session-start hook both access epics.db. SQLite handles this via WAL mode but timeout/retry needed for concurrent writes.
- **_find_matching_group() Ollama dependency**: Wiring semantic grouping into process_session_corrections() makes correction detection depend on Ollama being available. Must preserve fallback to exact text match when Ollama is down.

### Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Semantic grouping merges unrelated corrections | Med | Med | Use existing 0.55 threshold; add logging to review groupings; manual dismiss for false merges |
| Session-start hook exceeds 10s timeout with new DB queries | High | Low | decision_preferences query is a simple SELECT with LIMIT; benchmark before shipping |
| Generated compliance hooks interfere with legitimate tool use | Med | Low | Warn-only mode (never exit 2); user can dismiss in settings.json |
| Ollama unavailable breaks semantic grouping | Med | Med | Fallback to exact text match when embedding fails; same pattern as existing dedup |
| settings.json corruption from hook generator | High | Low | Atomic write via tmp+rename already implemented in hook_generator.py |

### Cost Estimate
**Development complexity:**
| Feature | Size | Notes |
|---------|------|-------|
| 1. Create decision_preferences table | S | Schema migration, ~15 lines Python in existing migration block |
| 2. Fix Stage 5 hook generation | S | mkdir + settings.json cleanup, ~10 lines |
| 3. Wire semantic correction grouping | M | Replace exact match with _find_matching_group(), add fallback, test thresholds |
| 4. Render decision scores | S | New query + rendering block in session-start, ~30 lines Python |
| 5. Data cleanup + docs | S | One-time migration + CLAUDE.md edit |

## Test Strategy

### Critical paths
- After schema migration, `sqlite3 epics.db '.tables'` includes `decision_preferences`
- Stage 2 of stop_processor no longer logs "skipped (no decision_preferences table)"
- After a session with corrections near a decision, decision_preferences.signal_score is decremented
- Promoted correction themes produce executable .sh files in hooks/compliance/
- rendered-prefs.md shows "Decision Health" section with negatively-scored decisions
- Semantically similar corrections (different wording, same meaning) merge into one group

### Edge cases
- Ollama unavailable: semantic grouping falls back to exact match, Stage 2 still runs (text overlap doesn't need embeddings)
- Empty decision_preferences table: session-start renders "No decision health data yet" or omits section
- Hook generator produces script for non-hookable theme: classify_hookability returns hookable=false, no script written, logged to OpenMemory
- Concurrent epics.db access: stop_processor background write + session-start read don't cause "database locked"
- MAX_EMBEDDING_CALLS_PER_SESSION = 5: correction detection respects limit even with semantic grouping enabled

### Integration boundaries
- decision_preferences schema must match between tools_pm_decisions.py (Gemini MCP) and signal_processor.py (stop hook) — same column names, types, defaults
- Hook generator settings.json writes must not corrupt existing hook entries (atomic write verified by 16 self-tests)
- om_write() tag whitelist: any new tags for decision scoring require updating ALLOWED_TAGS, BUDGETS, CLAUDE.md, refs/orch-memory.md (4-file coordination)
- rendered-prefs.md format must remain compatible with CLAUDE.md @import — markdown list items, no frontmatter

### What NOT to test
- Hook registration in settings.json — fails obviously if the JSON is malformed
- Ollama health check mechanics — existing curl-based check works; we're testing behavior when it fails, not the check itself
- Schema migration idempotency — SQLite CREATE TABLE IF NOT EXISTS handles this

## Blast Radius
- **hooks/lib/stop_processor.py**: Background process. Failures are silent — only symptom is rendered-prefs.md stops updating. Dependents: session-learning-check.sh (spawner). Runtime contracts: 5-stage sequential execution, PID lockfile.
- **hooks/lib/signal_processor.py**: Import error crashes all of stop_processor Stage 1. Trust score failure at session start produces fallback message. Dependents: stop_processor.py, load-session-context.sh. Contract: process_session_corrections() interface, compute_trust_scores() return shape.
- **hooks/load-session-context.sh**: Synchronous, 10s timeout. Hanging Python kills entire session context. Dependents: every session. Contract: must output CLAUDE.md, ORCHESTRATION.md, rendered-prefs.md, trust scores, agenda.
- **hooks/lib/hook_generator.py**: 16 self-tests. Atomic settings.json writes. Failure only affects hook generation — low operational impact. Dependents: stop_processor Stage 5.
- **CLAUDE.md**: Affects every session's behavioral instructions. Inaccurate references mislead Claude about available infrastructure.
- Confidence: **exhaustive** (scout traced all 4 write targets with 30+ locations, 0 significant blind spots)

## Success Criteria
- A user correction that reaches count >= 3 produces all three conditioning effects: text in rendered-prefs.md, a compliance hook in hooks/compliance/, and (if near a decision) a signal_score decrement in decision_preferences
- Session start displays both "Behavioral Preferences" and "Decision Health" sections when data exists
- Semantically identical corrections with different wording merge into one group (reducing the 48 accumulating entries)
- Stage 2 and Stage 5 of stop_processor execute without skipping (verified via /tmp/stop-processor-*.log)
- No increase in session-start time (target: <2s total for all context injection)
- Dead settings.json hook references are cleaned; CLAUDE.md accurately reflects infrastructure state

## Decisions
- **Promotion mechanism**: Keep count-based threshold (>= 3) over LLM-driven promotion. Simpler, more predictable, no extra LLM call. Research shows LLM-driven is the trend but our approach is more structured for a single-user system. (recommended)
- **Preference filtering**: Monolithic injection (all prefs every session) over context-aware retrieval. At 7 prefs, token cost is negligible. Revisit when count exceeds 20. (recommended)
- **Semantic grouping**: Wire _find_matching_group() with Ollama fallback to exact match. Research strongly supports semantic over exact. Dead code already exists. (recommended)
- **Hook enforcement level**: Warn-only (stderr warning, exit 0) over blocking (exit 2). Safer, avoids false-positive lockouts. Can escalate to blocking per-hook later. (recommended)
- **Temporal supersession**: Defer. Manual dismissal suffices at current scale. (recommended)
- **Observer/generalizer pass**: Cut. High complexity, uncertain value over threshold-based promotion. Reconsider after measuring correction recurrence rates. (recommended)

## Constraints
- Python/Bash/SQL infrastructure — no new languages or runtimes
- SQLite databases: epics.db, run-state.db, openmemory.sqlite
- Ollama nomic-embed-text for all embeddings — graceful degradation required
- Existing decisions: correction detection in signal_processor.py (d-43), unified entry point (d-75), three persistence surfaces only (d-79), layered trust (d-90)
- No training-time RLHF, no fine-tuning — inference-time behavioral conditioning only
- Must not disrupt working pipeline stages (1, 3, 4)

## Reference
- [Letta Memory Architecture](https://docs.letta.com/guides/agents/memory/) — OS-inspired tiered memory
- [LangMem Conceptual Guide](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/) — semantic/episodic/procedural memory types
- [CIPHER: Learning Latent Preference from User Edits](https://arxiv.org/abs/2404.15269) — context-aware preference retrieval
- [CHIEF: Causal Hierarchical Failure Attribution](https://arxiv.org/html/2602.23701) — state of the art in decision-outcome correlation (52% step accuracy)
- [Policy-as-Prompt Synthesis](https://arxiv.org/html/2509.23994v1) — document-to-rule guardrail generation
- [Pro2Guard: Probabilistic Runtime Enforcement](https://arxiv.org/html/2508.00500) — trace-informed enforcement (closest to auto-generation)
- [MemGPT Paper](https://arxiv.org/abs/2310.08560) — original hierarchical memory architecture
- [2025 AI Agent Index](https://arxiv.org/html/2602.17753v1) — 40%+ deployed agents lack trace infrastructure
