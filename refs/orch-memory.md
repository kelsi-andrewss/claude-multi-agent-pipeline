# Memory Reference — OpenMemory-Primary Architecture

---

## Architecture

Two layers:
1. **Eager** — CLAUDE.md, ORCHESTRATION.md, behavioral-prefs.md. Loaded every session.
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

Stop hook flow:
1. Detect corrections in transcript (imperative redirect, frustration, meta-comment patterns)
2. Write to `correction_groups` table (theme, count, dates)
3. When count >= 3: auto-promote → behavioral-prefs.md + OpenMemory via om_write
4. Prefixed with "(auto-distilled)" for optional refinement at session start

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
