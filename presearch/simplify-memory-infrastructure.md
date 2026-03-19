# Simplify Memory Infrastructure

## Overview

The behavioral learning pipeline is partially broken (rendered-prefs.md blank due to schema migration bug) and overbuilt (7 persistence surfaces, 49% OpenMemory bloat, duplicate embedding code, synchronous Stop hook killing Ollama work via 10s timeout). This refactor fixes the pipeline, eliminates dead surfaces, and makes the Stop hook non-blocking.

## Summary

Fix the broken behavioral learning pipeline (schema migration bug makes rendered-prefs.md blank). Kill 4 of 7 persistence surfaces (correction-tallies.jsonl, om-ops.json, tool-learnings.md, corrections.md). Purge 366 legacy entries from OpenMemory (49% bloat). Extract shared embedding utilities from duplicated code in signal_processor.py and om_write.py. Make Stop hook non-blocking by splitting fast sections (mtime check) from slow sections (signal processing, distillation) via background subprocess. Accept Ollama dependency per decision-74 but add visible warning when degraded.

## Features

### MVP
0. **Fix schema migration + purge bloat**: Run correction_groups schema migration (add text/source columns, backfill promoted entries). Purge 366 legacy OpenMemory entries. Delete correction-tallies.jsonl and om-ops.json. Extract shared embedding_utils.py. Fix Stop hook tool-learnings sync (stop re-embedding static entries).
1. **Kill corrections.md + consolidate pipeline**: Replace corrections.md with direct DB writes to correction_groups. Update CLAUDE.md correction logging instructions. Update signal_processor.py to stop parsing corrections.md. Remove _parse_corrections() function. Ensure correction_groups is the single source of truth.
2. **Async Stop hook**: Split session-learning-check.sh into fast path (mtime check, <1s) and slow path (signal processing, session summary, distillation). Slow path runs as background subprocess via nohup. Add Ollama-down warning to Stop hook output.

## Technical Research

### Architecture

**Persistence surface reduction**: 7 surfaces → 3:

| Surface | Status | Action |
|---------|--------|--------|
| corrections.md | KILL | Replace with direct correction_groups DB writes |
| correction_groups (epics.db) | KEEP | Single source of truth for corrections |
| correction-tallies.jsonl | KILL | Dead code, 2 entries, replaced by correction_groups status |
| rendered-prefs.md | KEEP | Generated sidecar, fix schema migration to unblock |
| tool-learnings.md | KILL | Move to OpenMemory only, stop dual-writing |
| openmemory.sqlite | KEEP | Purge bloat, keep as semantic memory store |
| om-ops.json | KILL | Write-only diagnostic, zero readers, replace with stderr |

**Async Stop hook architecture**:
```
session-learning-check.sh
├── Section 1: Mtime comparison (SYNC, <100ms)
├── Section 2: Spawn background processor (SYNC, <50ms)
│   └── nohup python3 hooks/lib/stop_processor.py \
│       --transcript $TRANSCRIPT_PATH \
│       --db $DB_FILE \
│       --session $SESSION_ID \
│       --project $HOME/.claude \
│       > /tmp/stop-processor-$SESSION_ID.log 2>&1 &
│       disown
└── Exit 0
```

`stop_processor.py` handles: correction detection, signal processing, session summary, auto-distillation. Uses SQLite WAL mode with `busy_timeout=5000` to avoid lock contention with session-start reads.

### Files changed

| File | Action | Purpose |
|------|--------|---------|
| `hooks/lib/embedding_utils.py` | NEW | Shared _get_embedding, _cosine_similarity, blob serialization (~50 lines) |
| `hooks/lib/stop_processor.py` | NEW | Background processor for slow Stop hook sections |
| `hooks/lib/signal_processor.py` | MODIFY | Import from embedding_utils.py. Remove _parse_corrections() (corrections.md parser). Remove corrections.md dependency. |
| `hooks/lib/om_write.py` | MODIFY | Import from embedding_utils.py. Remove _log_op() (om-ops.json writer). Log to stderr instead. |
| `hooks/session-learning-check.sh` | MODIFY | Remove sections 3-6. Replace with nohup spawn of stop_processor.py. Remove tool-learnings.md sync (section 5). Add Ollama-down warning. |
| `hooks/load-session-context.sh` | MODIFY | Fix schema migration check. Verify correction_groups has text column before rendering. |
| `CLAUDE.md` | MODIFY | Update correction logging instructions: write to correction_groups DB instead of corrections.md |
| `ORCHESTRATION.md` | MODIFY | Update §13 (Memory) to reflect 3 surfaces instead of 7. Update behavioral learning section. |
| `refs/orch-memory.md` | MODIFY | Update architecture description |

### Schema migration (correction_groups)

Current schema is missing `text` and `source` columns. The migration in session-learning-check.sh Section 6b attempts to add them via table rebuild but the conditional check may not trigger.

**Fix**: Direct migration script that:
1. Checks `PRAGMA table_info(correction_groups)` for text/source columns
2. If missing: `ALTER TABLE correction_groups ADD COLUMN text TEXT DEFAULT ''` and `ALTER TABLE correction_groups ADD COLUMN source TEXT DEFAULT 'auto'`
3. Backfill: `UPDATE correction_groups SET text = 'User corrected ' || count || 'x on: ' || substr(theme, 1, 200) WHERE status = 'promoted' AND (text IS NULL OR text = '')`
4. Create index: `CREATE INDEX IF NOT EXISTS idx_correction_groups_status ON correction_groups(status)`

### OpenMemory purge

One-time script:
```sql
-- Delete transcript entries (predate budget system)
DELETE FROM memories WHERE tags LIKE '%transcript%';
-- Delete legacy correction/behavioral entries outside ALLOWED_TAGS
DELETE FROM memories WHERE tags NOT LIKE '%tool-learning%'
  AND tags NOT LIKE '%behavioral-pref%'
  AND tags NOT LIKE '%decision%'
  AND tags NOT LIKE '%prompt-pattern%'
  AND tags NOT LIKE '%session-summary%'
  AND tags NOT LIKE '%critique-learning%'
  AND tags NOT LIKE '%gemini-blind-spot%';
VACUUM;
```

Expected: ~366 entries removed, DB shrinks from 4.5MB to ~2.3MB.

### Correction logging without corrections.md

Current flow: Claude appends markdown to corrections.md → Stop hook parses → embeds → groups in DB.

New flow: Claude calls a script that writes directly to correction_groups:
```bash
# ~/.claude/scripts/log-correction.sh
# Usage: log-correction.sh "theme text" [date]
```

The script:
1. Inserts into correction_groups with status='accumulating', source='manual'
2. If Ollama available, computes embedding for grouping
3. If matching group exists (embedding similarity ≥ 0.85), increments count instead
4. Returns JSON: `{status, group_id, count}`

CLAUDE.md instruction changes from "Append to corrections.md" to "Run `~/.claude/scripts/log-correction.sh '<description>'`".

### Patterns

- **Background process safety**: PID lockfile at `/tmp/stop-processor-<session>.pid`. Check before spawning. Kill stale (>5 min) processes.
- **SQLite WAL mode**: All background writes use `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`
- **Shared imports**: `from hooks.lib.embedding_utils import get_embedding, cosine_similarity, embedding_to_blob, blob_to_embedding`

### Gotchas

- **Schema migration idempotency**: The migration must be safe to run multiple times. Use `ALTER TABLE ... ADD COLUMN` with try/except (SQLite errors on duplicate column add).
- **corrections.md has 30+ existing entries**: These need a one-time ingestion into correction_groups before deleting the file. Run the existing _parse_corrections() one final time.
- **Stop hook timeout interaction**: The current 10s async timeout may kill the background spawn before it detaches. Ensure nohup/disown happens in the first 100ms of the hook.
- **CLAUDE.md change affects all sessions**: After updating correction logging instructions, Claude will try to run log-correction.sh. The script must exist before the CLAUDE.md change ships.
- **tool-learnings.md still referenced by CLAUDE.md**: Update CLAUDE.md to remove "Append a one-liner to tool-learnings.md" instruction when eliminating that surface.
- **rendered-prefs.md regression test**: After schema migration, verify rendered-prefs.md actually contains preference text, not just the header.

### Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Schema migration corrupts correction_groups | High — loses behavioral data | Low — ALTER TABLE ADD COLUMN is safe | Backup epics.db before migration. Use ALTER TABLE not table rebuild. |
| Background Stop hook never completes (killed by system) | Med — corrections not processed | Med — depends on OS process management | PID lockfile + stale process detection at next session start |
| corrections.md deletion loses historical audit trail | Low — data is in correction_groups | Low | One-time ingestion before deletion. Git history preserves the file. |
| OpenMemory purge deletes useful entries | Med — semantic search quality | Low — only removing entries with invalid tags | Dry-run query first. Log count before DELETE. |

## Test Strategy

### Critical paths
- Schema migration adds text/source columns to correction_groups and backfills promoted entries
- rendered-prefs.md renders actual preference text after migration (not blank)
- log-correction.sh inserts into correction_groups correctly (with and without Ollama)
- Background Stop hook process completes within 30s and writes to DB
- OpenMemory purge removes only entries outside ALLOWED_TAGS

### Edge cases
- Schema migration on DB that already has text/source columns (idempotent)
- Background process spawn when previous session's process is still running (lockfile check)
- log-correction.sh when Ollama is down (should still insert, skip embedding)
- Session start after background Stop hook was killed (stale data detection)

### Integration boundaries
- rendered-prefs.md generation reads from correction_groups — schema must match
- CLAUDE.md correction instructions must match available script interface
- Background process writes must not lock out session-start reads (WAL mode)

### What NOT to test
- Ollama embedding quality — decision-74 already validated this
- OpenMemory semantic search after purge — the purged entries weren't being searched anyway
- Stop hook timing — async behavior depends on OS, not deterministic

## Decisions

- **Ollama dependency**: Accept + add visible warning when down. No fallback. (user decision, per decision-74)
- **Dedup strategy**: Keep embedding-based. Fix root causes (purge bloat, stop re-embedding static entries). (user decision)
- **Surface elimination**: Kill 4 (corrections.md, correction-tallies.jsonl, om-ops.json, tool-learnings.md). Reduce to 3. (user decision)
- **Async Stop hook**: Background subprocess via nohup. Fast sections stay sync. (user decision)
- **Schema migration**: ALTER TABLE ADD COLUMN approach, not table rebuild. Backfill promoted entries. (Claude recommendation)
- **Shared embedding code**: Extract to hooks/lib/embedding_utils.py. Both signal_processor.py and om_write.py import. (Claude recommendation)
- **Correction logging**: Replace corrections.md append with log-correction.sh script writing directly to DB. (Claude recommendation)

## Constraints

- decision-74 (ACTIVE): semantic embeddings for correction detection, no regex fallback
- decision-73 (ACTIVE): rendered-prefs.md sidecar via @import for compaction resilience
- decision-75 (ACTIVE): single authority for correction pipeline in signal_processor.py
- bash/python only, no new dependencies
- epics.db ownership model unchanged (Gemini writes via pm_*, Claude writes plan_file + state)
