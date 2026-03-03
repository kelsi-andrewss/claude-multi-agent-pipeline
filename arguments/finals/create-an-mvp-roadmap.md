# Argue: create an mvp roadmap
**Type**: general  **Rounds**: 4  **Converged**: no
**Date**: 2026-03-03

## Synthesis

**Positions not fully reconciled after 4 round(s).**

**Key tension:** Whether to use Pinecone (managed, production-ready) or a local vector DB (ChromaDB/LanceDB, faster iteration) during the 24-hour MVP sprint.

**Best available synthesis:**

### MVP Roadmap for LegacyLens (24 hours)

**Build order (data-first):**

| Hours | Phase | Deliverable |
|-------|-------|-------------|
| 0-2 | Parser validation | `SubroutineExtractor` that handles Fortran 77 fixed-form: column-1 comments, 6th-column continuations, `SUBROUTINE`/`FUNCTION`/`END` boundaries |
| 2-5 | Ingestion + embedding cache | Generate embeddings via OpenAI, cache to local `.jsonl`. Do NOT upsert to any vector DB yet. |
| 5-7 | Vector DB sync | Batch-upsert cached embeddings to Pinecone (or local store) |
| 7-12 | Retrieval loop | Query -> Embed -> Search -> Format Context pipeline |
| 12-18 | LLM + citations | System prompt tuning, file/line citation enforcement, streaming |
| 18-24 | CLI UX + evaluation | `rich` syntax highlighting, 10-query eval suite, polish |

**Key decisions:**

1. **Web UI: strictly deferred.** No frontend in the 24hr window. CLI only.
2. **Similarity threshold: 0.5 not 0.7.** Legacy code queries often score 0.6-0.7 for correct results. Pass scores to the LLM and let it judge relevance.
3. **Fortran edge cases: ignore for MVP.** Skip `ENTRY`, `BLOCK DATA`, `INCLUDE`, multi-file modules. They're <5% of LAPACK logic but 50% of parsing complexity.
4. **Cache embeddings locally first.** Write to `.jsonl` before any vector DB upsert — protects against re-embedding costs if index config is wrong.
5. **Initialize Pinecone index in Hour 0.** Free tier has cold-start latency; kick it off early.

**The unresolved vector DB question:**

- **Pinecone camp:** Avoids Day 2 migration when adding web UI. Production-ready from the start.
- **Local DB camp:** Sub-millisecond iteration during the volatile parse-fix-reindex loop. Re-indexing 3,500 vectors locally takes seconds vs network round-trips.
- **Synthesis resolution:** Use a thin abstraction layer (~20 lines) over vector DB calls. Start with Pinecone as the presearch specified — the migration cost is real but manageable. The "over-fetching + Python filtering" trick (top-50 then filter in Python) decouples retrieval logic from any DB's filtering DSL, making a future swap trivial. This keeps the presearch architecture intact while mitigating the lock-in risk.

**Riskiest integration points:**
1. Fortran line continuations (column 6) breaking the parser
2. OpenAI rate limits on 2.4M token burst (use tenacity retries)
3. Pinecone free tier cold-start delays on new indexes

**Minimum evaluation strategy:**
- 5 "easy" queries (subroutine name lookups: "What does DGESV do?")
- 5 "hard" queries (conceptual: "How does LU factorization work?")
- Pass criterion: correct subroutine in top-3 for all easy queries, top-5 for hard queries

## Tension summary

The remaining tension centers on whether the benefits of local iteration speed and "over-fetching" abstractions outweigh the risk of architectural debt and integration friction when transitioning to a managed production environment.
