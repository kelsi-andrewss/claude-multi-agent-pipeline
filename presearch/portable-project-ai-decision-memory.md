# Portable Per-Project AI Decision Memory

## Problem Statement
**What problem?** Architectural decisions are stored globally in `~/.claude/.claude/epics.db` and `openmemory.sqlite`, not per-project. When cloning a repo on a new machine or starting a new AI session, critical context about "why the code is this way" is lost. Legacy codebases have implicit decisions that no one documented — AI tools break them because they look like bugs.

**Why fix it?** Without this, every new AI session on a legacy codebase is a liability. The AI will "fix" intentional workarounds, violate compliance constraints it doesn't know about, and refactor away load-bearing hacks. The cost compounds with codebase size — a 100k+ LOC codebase has hundreds of implicit decisions.

**Why integral?** This project builds developer tooling. The value proposition is AI that works WITH the codebase's history, not against it. Per-project decision memory is the difference between an AI that understands context and one that keeps making the same mistakes every session.

**End goal:** An AI working on any file automatically sees the 2-5 most relevant decisions for that file. New projects can run a discovery scan and have a populated decision store in minutes. The store travels with the repo — clone it on a new machine, decisions just work. No Ollama, no external services required.

## Overview

A decentralized, repository-local decision memory layer. Decisions are stored in a git-friendly SQL dump (`.claude/decisions.sql`) that rebuilds to a local SQLite + sqlite-vec database on first query. Embeddings are generated via FastEmbed/ONNX (no Ollama required) using nomic-embed-text-v1.5 at 256d Matryoshka dimensions. Edit-time injection surfaces relevant decisions through three layers: MCP hook-triggered auto-injection, generated glob-rule files as fallback, and explicit query as escape hatch.

This complements the existing OpenMemory system (global, cross-project) — it does not replace it. The per-project DB lives in the target project's `.claude/` directory and travels with the repo via git.

## Summary

Portable per-project AI decision memory using a hybrid SQL dump + local sqlite-vec store. Decisions are recorded explicitly (MCP tool) or discovered from code comments/commits (phased auto-discovery). File-level associations enable edit-time injection — when the AI touches a file, relevant decisions surface automatically. Stack: Python library + Claude Code MCP server, FastEmbed ONNX for portable embeddings at 256d, sqlite-vec for vector search, FTS5 for keyword fallback. Phased delivery: v1 ships manual recording + edit-time injection + comment extraction. v2 adds LLM-based implicit decision discovery.

## Features

### MVP
0. **Bootstrap**: Create Python package structure (`decision_memory/`), install deps (sqlite-vec, fastembed), create shared types/interfaces, set up pytest config, create `.env.example`, register MCP server
   - `decision_memory/__init__.py`, `decision_memory/store.py`, `decision_memory/embeddings.py`
   - `decision_memory/schema.sql`, `setup.py` or `pyproject.toml`

1. **Core storage engine**: SQL dump portability + local sqlite-vec rebuild
   - `.claude/decisions.sql` (git-committed source of truth)
   - Local `.claude/decisions.db` (gitignored, rebuilt from dump)
   - Hash-based staleness check: SHA-256 of decisions.sql stored in decisions.db metadata table
   - First query triggers rebuild if hash mismatch or DB missing
   - `decision_memory/store.py`, `decision_memory/dump.py`

2. **Embedding layer**: FastEmbed ONNX + 256d Matryoshka + hybrid search
   - FastEmbed generates embeddings without Ollama (bge-small-en-v1.5 default, nomic-embed-text-v1.5 preferred)
   - sqlite-vec virtual table for vector KNN queries
   - FTS5 virtual table for keyword fallback when model unavailable
   - RRF (Reciprocal Rank Fusion) merges vector + keyword results
   - `decision_memory/embeddings.py`, `decision_memory/search.py`

3. **MCP server + recording tools**: record, query, sync decisions
   - `record_project_decision(content, reasoning, file_patterns[], status, source)`
   - `query_project_decisions(query_text?, active_files[]?, limit=5)` — hybrid search
   - `sync_decision_store()` — force rebuild from SQL dump
   - `decision_memory/mcp_server.py`

4. **Edit-time context injection**: three-layer architecture
   - Layer 1 (primary): Claude Code hook on UserPromptSubmit → calls MCP `query_project_decisions(active_files=<current_files>)` → injects top decisions into context
   - Layer 2 (fallback): Generated `.claude/rules/decisions-*.md` files from DB, one per file glob pattern. Regenerated on decision changes. Works without MCP server running.
   - Layer 3 (escape hatch): AI explicitly calls `search_project_decisions(query)` MCP tool for semantic search beyond file-scoped matches
   - `hooks/inject-project-decisions.sh`, `decision_memory/rules_generator.py`

### Phase 2
5. **Auto-discovery v1**: comment/commit extraction (proven, low FP)
   - Scan for SATD markers: TODO, HACK, WORKAROUND, XXX, FIXME with context
   - Parse git commit messages for decision-related patterns ("because", "instead of", "reverted", "constraint")
   - Propose candidate decisions with confidence scores for human review
   - `decision_memory/discover.py`

6. **Decision lifecycle**: status tracking + supersession chain
   - Status field: active → deprecated → superseded → violated
   - `superseded_by` links to replacement decision
   - Automatic staleness detection: decisions linked to deleted files
   - `decision_memory/lifecycle.py`

7. **Incremental indexing**: content-hash-based scan optimization
   - SHA-256 per decision text, skip re-embedding unchanged decisions
   - File watcher for decisions.sql changes (optional, for IDE integration)
   - `decision_memory/indexer.py`

### Cut
- Replacing OpenMemory (this complements it)
- Real-time multi-user sync beyond standard git workflows
- Language-specific AST parsing (file/function level only in v1)
- LLM-based implicit decision discovery (deferred to v2+ after v1 validation)
- Cross-tool portability format (Cursor/Windsurf) — design for it but don't implement adapters yet

## Technical Research

### Architecture
**Sidecar Database Pattern**: The SQL dump (`.claude/decisions.sql`) is the portable source of truth. The local SQLite DB (`.claude/decisions.db`) is a computed artifact — gitignored, rebuilt from the dump. This avoids binary merge conflicts while keeping query performance.

**Rebuild flow:**
1. On first MCP tool call or hook invocation, check if `decisions.db` exists
2. If missing: execute `decisions.sql` to create DB, build sqlite-vec index, build FTS5 index, store SHA-256 of dump in `_metadata` table
3. If exists: compare stored hash vs current `decisions.sql` hash. If mismatch, drop and rebuild.
4. Rebuild is idempotent — the SQL dump contains `CREATE TABLE IF NOT EXISTS` and `INSERT OR REPLACE`

**Embedding independence**: This system uses FastEmbed + 256d vectors. The existing orchestration system keeps Ollama + 768d vectors. They are separate systems with separate DBs. No migration needed.

### Patterns
- **Embedding**: FastEmbed via `fastembed.TextEmbedding("nomic-ai/nomic-embed-text-v1.5")` with `embed()` for documents, `query_embed()` for queries (handles task prefixes automatically)
- **Vector search**: sqlite-vec virtual table with `vec_distance_l2()` for KNN
- **Keyword search**: FTS5 with `rank` for BM25 scoring
- **Hybrid merge**: RRF with k=60 — `1/(k + rank_vector) + 1/(k + rank_keyword)`
- **Error handling**: Graceful degradation — if FastEmbed model not downloaded, fall back to FTS5-only. If decisions.db doesn't exist, rebuild silently. Never block the AI session.
- **Naming**: `decision_memory.*` for the library, `project_decision_*` for MCP tool names (avoid collision with existing `pm_*` tools)

### Data Model

```sql
-- Source of truth (in .claude/decisions.sql, committed to git)
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    reasoning TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deprecated', 'superseded', 'violated')),
    source TEXT NOT NULL DEFAULT 'human'
        CHECK (source IN ('human', 'ai-discovered', 'ai-proposed')),
    superseded_by INTEGER REFERENCES decisions(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decision_scopes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('file', 'pattern', 'tech')),
    scope_value TEXT NOT NULL
);

-- Local only (in .claude/decisions.db, gitignored)
CREATE TABLE IF NOT EXISTS _metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- _metadata stores: dump_hash, last_rebuild, model_name, embedding_dim

-- sqlite-vec virtual table (local only)
CREATE VIRTUAL TABLE IF NOT EXISTS decision_embeddings USING vec0(
    decision_id INTEGER PRIMARY KEY,
    embedding float[256]
);

-- FTS5 virtual table (local only)
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    content, reasoning, content=decisions, content_rowid=id
);
```

### Shared Interfaces
- `decision_memory/store.py`: `DecisionStore` class — `record()`, `query()`, `rebuild()`, `dump()` (used by features 1, 3, 4, 5)
- `decision_memory/embeddings.py`: `get_embedding_portable()`, `hybrid_search()` (used by features 2, 3, 4)
- `decision_memory/types.py`: `Decision`, `DecisionScope`, `SearchResult` dataclasses (used by all features)

### Dependencies
- `sqlite-vec` — portable vector search in SQLite (zero C++ deps)
- `fastembed` — ONNX-based embedding generation (no Ollama needed)
- `mcp>=1.26.0` — MCP server framework (consistent with existing Gemini MCP server)
- `pytest` — testing

No additional dependencies. `sqlite3` and `json` are stdlib.

### Gotchas
- **Git noise**: Large SQL dumps clutter git history. Mitigation: sorted INSERT statements (one decision per line), consistent formatting for clean diffs.
- **First-query latency**: Initial rebuild + embedding generation for N decisions takes ~N*15ms. For 100 decisions, ~1.5 seconds. For 1000, ~15 seconds. Add progress indicator for >5s rebuilds.
- **Model download**: FastEmbed downloads the ONNX model on first use (~100MB for nomic). Must happen once per machine. Document this in README.
- **SQL dump atomicity**: Writing the dump mid-session could race with git operations. Mitigation: write to `.tmp` then atomic rename.
- **decision-79 conflict**: This adds persistence surface #4. Justification: the new surface lives in the TARGET project's repo, not in `~/.claude/`. It's per-project, not per-user infrastructure.

### Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| FastEmbed model changes break embedding compatibility | High | Low | Pin model version in config, store model name in _metadata, validate on rebuild |
| SQL dump format changes break portability | High | Low | Version field in dump header, migration logic in rebuild |
| sqlite-vec not available on exotic platforms | Med | Low | Fall back to Python brute-force cosine (existing pattern from embedding_utils.py) |
| Auto-discovery false positives erode trust | High | High | Human-in-the-loop review for all AI-proposed decisions, confidence scoring |
| Git merge conflicts in decisions.sql | Med | Med | Sorted INSERT format, one decision per line, standard SQL conflict resolution |

### Development Complexity
| Feature | Size | Notes |
|---------|------|-------|
| 0. Bootstrap | S | Package structure, deps, MCP registration |
| 1. Core storage engine | M | SQL dump/rebuild, hash check, atomic writes |
| 2. Embedding layer | M | FastEmbed integration, sqlite-vec, FTS5, RRF hybrid |
| 3. MCP server + tools | M | 3 MCP tools, integration with existing FastMCP pattern |
| 4. Edit-time injection | M | Hook script, rules generator, three-layer architecture |
| 5. Auto-discovery v1 | L | Comment parsing, commit analysis, candidate proposal |
| 6. Decision lifecycle | S | Status field logic, supersession chain |
| 7. Incremental indexing | S | Content hash, skip unchanged |

## Test Strategy

### Critical paths
- SQL dump round-trip: record decision → dump to SQL → delete DB → rebuild from dump → query returns same decision
- Hybrid search accuracy: vector search returns relevant decisions for file-scoped queries
- Edit-time injection: hook receives file paths → MCP returns top decisions → context includes them
- Graceful degradation: FastEmbed model missing → FTS5-only search still works
- Portability: clone repo with decisions.sql → first query rebuilds DB → decisions queryable

### Edge cases
- Empty decisions.sql (new project, no decisions yet)
- decisions.db exists but decisions.sql was updated (hash mismatch → rebuild)
- decisions.db exists but decisions.sql was deleted (orphaned DB → clear and warn)
- Decision with no file scopes (global decision) — should match any file query
- Concurrent writes: two MCP calls try to record simultaneously
- Very long decision text (>8192 tokens, exceeds embedding context window) — truncate with warning

### Integration boundaries
- MCP tool registration: new server must not conflict with existing Gemini MCP server tool names
- Hook integration: new inject-project-decisions.sh must coexist with existing inject-tier2-context.sh
- SQLite WAL mode: decisions.db must use WAL for concurrent read/write from hook + MCP server
- FastEmbed model cache: uses `~/.cache/fastembed/` by default — must work across projects

### What NOT to test
- sqlite-vec query mechanics (tested by sqlite-vec itself)
- FastEmbed embedding quality (tested by FastEmbed/Nomic)
- Git operations (decisions.sql management is the user's responsibility)
- MCP protocol transport (tested by mcp library)

## Blast Radius

- **`decision_memory/` (new package)**: No existing dependents. Safe to build in isolation.
- **`hooks/inject-project-decisions.sh` (new)**: Registered in settings.json alongside existing hooks. Must exit 0 always. Failure = no decision injection, session continues normally.
- **`.claude/decisions.sql` (new, per-project)**: First file in the per-project `.claude/` that is committed to git as structured data. Sets precedent for future per-project portable state.
- **Existing `hooks/lib/embedding_utils.py`**: NOT modified. The new system uses FastEmbed independently. No risk to existing Ollama-based embeddings.
- **Existing `hooks/lib/om_write.py`**: NOT modified. Decisions in the per-project DB are separate from OpenMemory shadows.
- **Existing MCP server (`mcp-servers/gemini/`)**: NOT modified. New MCP server is a separate registration.
- Confidence: **exhaustive** — scout confirmed no existing code paths are modified by MVP features.

## Success Criteria
- A developer clones a repo and the AI immediately knows decisions recorded by previous sessions — without Ollama, without external services
- Decision retrieval for file-scoped queries returns relevant results with >80% precision (measured by human review of top-5)
- Local DB rebuild takes <2 seconds for 100 decisions, <15 seconds for 1000
- The AI stops "fixing" intentional workarounds on files that have associated decisions
- New project discovery scan (comment/commit extraction) populates meaningful decisions within 5 minutes for a 100k LOC codebase

## Environment
- No external services required
- No API keys needed
- FastEmbed ONNX model downloads to `~/.cache/fastembed/` on first use (one-time, ~100MB)

## Decisions
- **Storage format**: Hybrid SQL dump — `.claude/decisions.sql` committed to git, local `.claude/decisions.db` rebuilt on demand (user decision)
- **Embedding model**: FastEmbed ONNX + nomic-embed-text-v1.5 at 256d Matryoshka — portable, no Ollama required (user decision)
- **Auto-discovery phasing**: v1 comment/commit extraction, v2 LLM implicit scan (user decision)
- **Injection architecture**: Three-layer — MCP hook auto, glob rules fallback, explicit query escape hatch (user decision)
- **Decision lifecycle**: active/deprecated/superseded/violated status fields (Gemini recommendation, agreed)
- **Provenance tracking**: source field (human/ai-discovered/ai-proposed) + linked file paths + commit hashes (Gemini recommendation, agreed)
- **Persistence surface justification**: New .decisions.db lives in target project repo, not ~/.claude/ — does not violate decision-79's 3-surface limit for user infrastructure (Claude assessment)
- **Embedding independence**: 256d FastEmbed for per-project DB, existing 768d Ollama for OpenMemory — separate systems, no migration (Claude assessment resolving scout conflict #5)

## Constraints
- Python 3.11+ required
- SQLite3 stdlib (no external DB)
- Must coexist with existing OpenMemory MCP server (separate registration)
- Must fit Claude Code hooks/MCP architecture (three-tier injection model)
- No language-specific AST parsing in v1
- pytest for testing
- No Ollama dependency for the per-project system (portability requirement)
- `.claude/decisions.db` must be gitignored; `.claude/decisions.sql` must be committed

## Reference
- [sqlite-vec documentation](https://alexgarcia.xyz/sqlite-vec/sqlite-vec.html) — vector search extension
- [FastEmbed documentation](https://qdrant.github.io/fastembed/) — ONNX embedding generation
- [nomic-embed-text-v1.5 model card](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) — Matryoshka dimensions
- [Hybrid search with sqlite-vec + FTS5](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html) — RRF implementation
- [Context Engineering for Coding Agents (Martin Fowler)](https://martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html) — edit-time injection patterns
- [Continue.dev + LanceDB architecture](https://lancedb.com/blog/the-future-of-ai-native-development-is-local-inside-continues-lancedb-powered-evolution/) — per-project memory reference
- [SATD Detection: A Decade Review](https://arxiv.org/html/2312.15020v3) — auto-discovery baseline
