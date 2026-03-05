# Memory Reference — Query/Store Templates & Protocols

Extracted from ORCHESTRATION.md §17. Loaded on demand during plan critique, coder prompt construction, and session debrief.

---

## When to query

**Plan critique** — before writing plan file:
```
openmemory_query(query="[story tech stack] [write-target file types] learnings failures", user_id="proj:<project>")
openmemory_query(query="[story tech stack] model capability", user_id="global")
```
Use results to check for known pitfalls. Skip if story has no write targets yet.

**Model selection** — when assigning coder model:
```
openmemory_query(query="[model name] [file type] failure success", user_id="global")
```
Consistent failures → escalate preemptively. Skip if no in-progress stories.

**Coder prompts** — after pitfalls from pm_list_patterns:
```
openmemory_query(query="[write-target file names] [tech stack] convention gotcha", user_id="proj:<project>")
```
Inject relevant results as text into coder prompt. Skip if query returns nothing.

**Session start** — only when Memory Briefing is present:
The briefing pre-fetches key memories. Additional query only if a story references tech not covered:
```
openmemory_query(query="[specific tech] learnings conventions", user_id="global")
```

**After correction verification**:
```
openmemory_query(query="correction [topic of correction]", user_id="proj:<project>")
```
Reinforce rather than duplicate if similar correction already stored.

---

## When to store

**After merge:**
```
openmemory_store(content="Merged [story-id]: [title]. Agent: [agent], Model: [model]. Friction: [count]. Key: [1-sentence observation].", tags=["session-summary"], user_id="proj:<project>")
```

**After coder failure/escalation:**
```
openmemory_store(content="[Model] failed on [task type]: [what went wrong, 1 sentence].", tags=["tool-learning"], user_id="global")
```

**After pm_add_decision:**
```
openmemory_store(content="Decision [id]: [summary]", tags=["decision", "<decision-id>"], user_id="proj:<project>")
```

**Before /clear:**
```
openmemory_store(content="Session [date]: Completed [stories]. Skills: [skills]. Friction: [count] ([categories]). Key: [takeaway].", tags=["session-summary"], user_id="proj:<project>")
```

**After key prompt logging:**
```
openmemory_store(content="[title]: [why-it-worked, 1-2 sentences]", tags=["prompt-pattern", "<category>"], user_id="global")
```

**When discovering a convention:**
```
openmemory_store(content="Convention: [what the pattern is and where it applies]", tags=["convention"], user_id="proj:<project>")
```

**After friction event (pattern promotion threshold, 3+ recurrences):**
```
openmemory_store(content="[Pattern]: [root cause] → [consequence]. Seen [N] times.", tags=["tool-learning"], user_id="global")
```

**After correction (manual or verified AUTO):**
```
openmemory_store(content="Correction: [what was wrong and what was right, 1 sentence]", tags=["correction"], user_id="proj:<project>")
```

**After informal decision:**
```
openmemory_store(content="Decision: [what was decided and why, 1-2 sentences]", tags=["decision-informal"], user_id="proj:<project>")
```

---

## Session-start synthesis

When `=== MEMORY BRIEFING ===` is present, before stating the session recommendation:

1. **Cross-reference** each in-progress/ready story against the briefing:
   - Tool learnings → model selection adjustments
   - Conventions → plan constraints
   - Session summaries → predictive warnings
   - Prompt patterns → note for plan critique

2. **Produce predictions** with confidence levels:
   ```
   Prediction: [what might happen] because [memory evidence].
   Confidence: high|medium|low ([N] supporting memories, score [X]).
   Adjustment: [what to do differently].
   ```
   - **High:** 3+ confirming memories OR 1 memory with `feedback_score >= 2.0`
   - **Medium:** 1-2 memories with `feedback_score > 0`
   - **Low:** inference without reinforcement history

3. **State adjustments concretely:** Not "be careful with React" but "escalate to Sonnet preemptively because Haiku has failed on this file type 3 times."

When briefing shows `(none yet)` across all categories: "No accumulated context — this session starts from scratch."

---

## Debrief reinforcement

At debrief (before `/clear`), for each completed story:

1. Read the plan file's `## Memory context` section (if present).
2. For each attributed memory:
   - **Validated** → `openmemory_reinforce(id="<memory-id>")`
   - **Contradicted** → store correction as tool-learning
   - **Irrelevant** → no action (natural decay)
3. For friction events WITHOUT a memory predicting them → store as new tool-learning.

**The compounding loop:**
```
Session N:   no memories → cold start → friction → stored
Session N+1: memory prefetched → prediction → adjustment → less friction → reinforced
Session N+2: reinforced memory → confident prediction → prevention → reinforced again
```

---

## Episodic Layer (Transcript Embeddings)

The memory system has three layers:

1. **Eager layer** — CLAUDE.md, ORCHESTRATION.md, behavioral-prefs.md. Loaded every session, always available.
2. **Lazy layer** — OpenMemory keyword queries (tool-learnings, conventions, decisions, session-summaries). Queried on demand via `openmemory_query`.
3. **Episodic layer** — Embedded transcript chunks from past conversations. Vector similarity search at session start.

### How episodic memories are stored

The Stop hook runs `hooks/lib/transcript_embedder.py` after each session. It:
- Parses the JSONL transcript into user/assistant turns
- Groups turns into ~500-token chunks
- Embeds each chunk via Ollama `nomic-embed-text`
- Stores into `openmemory.sqlite` with:
  - `primary_sector = "episodic"`
  - `tags = ["transcript", "session-YYYY-MM-DD"]`
  - `mean_vec` = little-endian float32 blob (`struct.pack("<Nf", ...)`)
  - `mean_dim` = embedding dimension count
  - `decay_lambda = 0.07` (~10-day half-life)
  - `salience = 0.3`
  - Dedup via MD5-based `simhash`

### How episodic memories are queried

At session start, `load-session-context.sh` builds a query from current context signals:
- Git branch name (split into words)
- Current directory
- In-progress story titles from epics.db
- Last 2 key exchanges from session-records.md

The query text is embedded via the same Ollama model, then cosine similarity is computed against all stored transcript chunks. Results are ranked by `similarity * exp(-0.07 * age_days)` — recent and relevant fragments rank highest. Top 5 fragments above a 0.3 similarity threshold appear in the memory briefing under "Transcript recall:".

### Parameters

| Parameter | Value | Rationale |
|---|---|---|
| Embedding model | nomic-embed-text | Same model used for OpenMemory; local via Ollama |
| Decay lambda | 0.07 | ~10-day half-life; old transcripts fade but persist |
| Similarity threshold | 0.3 | Filters noise; nomic-embed-text cosine scores tend low |
| Max results | 5 | Keeps briefing concise |
| Ollama timeout | 2s | Skip silently if Ollama is slow/down |
| Chunk truncation | 150 chars | Enough for context without overwhelming the briefing |

### Relationship to behavioral-prefs.md

`behavioral-prefs.md` is a distilled cache — human-readable preferences extracted from patterns across sessions. Transcript embeddings are the raw source material. The distillation pipeline (disagreements + outcomes + corrections -> behavioral-prefs) remains the authoritative path for behavioral learning. Episodic recall supplements it with raw conversational context that hasn't yet been distilled.

### Failure modes

- **Ollama down**: Transcript recall section is silently omitted. The Ollama health check earlier in the hook already warns about this.
- **No transcript memories**: Section is omitted entirely (no empty state shown).
- **Embedding timeout**: 2s timeout prevents blocking session start. Total hook budget is 10s.

---

## Graceful degradation

- Reads fail: skip silently, proceed with eager-layer context only.
- Writes fail: log entry in `tool-learnings.md` still captures it.
- Health check at session start warns when Ollama is unreachable.

## Reinforcement

When a memory directly influences a successful outcome, call `openmemory_reinforce`. Judgment call, not automatic. Don't reinforce speculatively.

## Subagent access

Coders do NOT query OpenMemory directly. Main session pre-fetches during coder prompt construction and injects as text.

## Tag taxonomy (use consistently — inconsistent tags fragment queries)

| Tag | Meaning |
|---|---|
| `tool-learning` | Model/tool capability observation |
| `convention` | Project convention or pattern |
| `decision` | Decision shadow (from pm_add_decision) |
| `decision-informal` | Decision from discussion, no DB entry |
| `correction` | Course correction |
| `session-summary` | Session episodic recap |
| `prompt-pattern` | Effective prompt approach |
| `bootstrap` | Initial seed data (set once) |
| `transcript` | Embedded conversation chunk (episodic layer) |

## Scoping

- Global (tool capabilities, prompt patterns): `user_id="global"`
- Per-project (conventions, decisions, sessions): `user_id="proj:<project-basename>"`

---

## Memory context in plan files

When memories influenced plan critique or model selection, include in plan file:
```markdown
## Memory context
- "[memory content, truncated]" (score: X) → [how it influenced this plan]
```
Creates traceable link between memory and outcome for debrief reinforcement.
