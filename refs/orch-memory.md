# Memory Reference — OpenMemory-Primary Architecture

---

## Architecture

Two layers:
1. **Eager** — CLAUDE.md, ORCHESTRATION.md, rendered-prefs.md (generated from DB). Loaded every session.
2. **Lazy** — OpenMemory queries at session start (top 5 per tag) and on demand.

All writes go through `hooks/lib/om_write.py`. No direct SQL inserts.

---

## Write gate (om_write.py)

**API:** `om_write(content, tags, user_id, sector, salience, decay_lambda) -> id | None`

**Enforcement:**
- Tag whitelist: only ALLOWED_TAGS accepted (behavioral-pref, tool-learning, decision, prompt-pattern, session-summary, critique-learning, gemini-blind-spot)
- Embedding-based dedup: cosine similarity >= 0.85 → update existing instead of inserting
- Fallback: MD5 simhash when Ollama unavailable
- Per-category budgets: auto-prune lowest-scoring when exceeded
- Ops logged to `tracking/om-ops.json`

**Budgets:**

| Tag | Budget | Write Source |
|---|---|---|
| `behavioral-pref` | 30 | Auto-distillation (stop hook) |
| `tool-learning` | 30 | Tool learning sync (stop hook) |
| `decision` | 50 | pm_add_decision shadow |
| `prompt-pattern` | 30 | Key-prompt logging |
| `session-summary` | 20 | Stop hook (1/session) |
| `critique-learning` | 30 | /critique skill (post-run) |
| `gemini-blind-spot` | 20 | /critique skill (Gemini escalation) |

---

## Session start query

`load-session-context.sh` runs:
1. `prune_expired()` — remove entries with decay-weighted score < 0.01
2. Query top 5 `behavioral-pref` entries by decay-weighted score
3. Query top 5 `tool-learning` entries by decay-weighted score
4. Output as compact `=== MEMORY ===` block

---

## Auto-distillation

Two write paths into `correction_groups` table:
- **Auto**: Stop hook detects corrections in transcript (semantic embedding against prototypes) → upserts to correction_groups
- **Manual**: Claude runs `scripts/log-correction.sh "<description>"` → inserts/increments in correction_groups

Promotion: when any group reaches count >= 3, auto-promoted to correction_groups DB (status='promoted') + OpenMemory via om_write. Prefixed with "(auto-distilled)" for optional refinement at session start.

---

## When to query (on demand)

**Plan critique:** `openmemory_query(query="[tech stack] learnings", user_id="global")`
**Model selection:** `openmemory_query(query="[model] [file type] failure", user_id="global")`
**Coder prompts:** `openmemory_query(query="[write-target] convention gotcha", user_id="proj:<project>")`

---

## When to store (on demand)

**After pm_add_decision:** `openmemory_store(content="Decision [id]: [summary]", tags=["decision", "<id>"], user_id="proj:<project>")`
**After key prompt:** `openmemory_store(content="[title]: [why]", tags=["prompt-pattern", "<category>"], user_id="global")`
**After coder failure:** `openmemory_store(content="[model] failed on [task]: [reason]", tags=["tool-learning"], user_id="global")`

All stores from Claude's session go through the MCP `openmemory_store` tool. All automated stores from hooks go through `om_write.py`.

---

## Scoping

- Global (tool capabilities, prompt patterns): `user_id="global"`
- Per-project (conventions, decisions, sessions): `user_id="proj:<project-basename>"`

---

## Graceful degradation

- Ollama down: simhash fallback for dedup, no embeddings stored, queries return empty
- OpenMemory DB missing: all operations silently skip
- Budget exceeded: lowest-scoring entry auto-pruned

---

## Trust Calibration

Trust scores are derived from merge_outcomes in run-state.db (populated by outcomes-parser.py from outcomes.md).

### Computation
- **Global score**: success_count / total_count across all merge_outcomes (default 0.5 when empty)
- **Domain score**: same formula filtered by domain_tag (derived from write-target paths)
- **Domain override**: auto-created when domain_score < global_score - 0.15 AND domain_count >= 3

### Trust levels
| Level | Threshold | Effect |
|---|---|---|
| High | >= 0.85 | Haiku eligible, auto-approve merges |
| Medium | >= 0.70 | Sonnet default, standard review |
| Low | < 0.70 | Sonnet default, escalation at 1 BLOCKING, mandatory approval |

### Graduation gate
- `min(global_score, domain_score)` determines effective trust for a story
- Domain overrides are lazy: created on divergence, not configured upfront
- Matches the correction→preference pipeline pattern (accumulate, then act)

### Session injection
- `load-session-context.sh` computes trust at session start
- Trust summary printed in session context output
- Domain overrides listed when present

### Anti-gaming
- Minimum 10 records before trust-informed selection activates
- Domain override requires 3+ samples to prevent noise
- Trust is advisory — Haiku threshold criteria (§2) still apply independently
