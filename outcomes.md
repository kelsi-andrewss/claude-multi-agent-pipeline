# Outcomes Log

Post-merge/rejection log for pattern recognition across sessions. Consulted on-demand, not loaded into every session.

## 2026-03-06 -- story-505 -- PostToolUse friction capture hook + settings.json registration
**Intent**: Auto-detect friction events from Agent tool results and log to friction-log.md
**Result**: merged
**Agent**: qf
**Model**: sonnet
**Cycle time**: ~3.5min
**Coder effort**: sonnet · 37486 tokens · 34 calls · 211s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-story execution; coder verified with multiple test inputs (BLOCKED, multi-match, clean, skip-type) and cleaned up after
**What failed**: nothing

## 2026-03-06 -- story-502 -- Add correction grouping to signal processor
**Intent**: Add correction grouping to signal processor
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: ~2min
**Coder effort**: haiku · 52594 tokens · 27 calls · 129s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file extension. Haiku followed the plan precisely — matched transcript_embedder patterns for Ollama integration.
**What failed**: nothing

## 2026-03-06 -- story-503 -- Update session start with triaged corrections and distillation detection
**Intent**: Update session start with triaged corrections and distillation detection
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: ~1.5min
**Coder effort**: haiku · 40333 tokens · 18 calls · 92s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean extension of existing shell script. Embedded Python block pattern well understood by Haiku.
**What failed**: nothing

```

## 2026-03-04 -- story-471 -- Fix Next.js 16 build failure: remove deprecated request.ip
**Intent**: Fix Next.js 16 build failure: remove deprecated request.ip from middleware.ts, use x-forwarded-for header fallback
**Result**: merged
**Agent**: qf
**Model**: sonnet
**Cycle time**: <1h
**Coder effort**: sonnet · 21222 tokens · 14 calls · 50s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file fix, quick-fixer was the right agent for a one-line change
**What failed**: nothing

## 2026-03-05 -- story-470 -- Fix Pinecone upsert type error
**Intent**: Fix Pinecone upsert type error
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: unknown
**Coder effort**: sonnet · 23347 tokens · 14 calls · 54s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file fix. Wrapped bare array in `{ records: [...] }` for Pinecone SDK v4+ compatibility.
**What failed**: nothing

## 2026-03-05 -- story-469 -- Fix AnswerStream infinite re-render loop on routine hover
**Intent**: Fix AnswerStream infinite re-render loop on routine hover
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: unknown
**Coder effort**: sonnet · 26662 tokens · 18 calls · 78s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file fix. Root cause identified markdownComponents useMemo depending on activeRoutine causing DOM destruction/recreation loop via ReactMarkdown. Ref pattern fix was surgical.
**What failed**: nothing

## 2026-03-04 -- story-462 -- Fix rate limiter — per-route limits
**Intent**: Fix rate limiter in src/middleware.ts — keep 10 req/min for /api/query, raise to 60 req/min for /api/games/* routes
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: ~5min
**Coder effort**: not captured
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file change, no conflicts, diff gate exact match
**What failed**: nothing
## [date] -- [story-id] -- [title]
**Intent**: what was the goal
**Result**: merged | rejected | reworked | blocked
**Agent**: quick-fixer | architect
**Model**: haiku | sonnet | opus
**Cycle time**: Xh (in-progress → done from epics.db)
**Coder effort**: [model] · [total_tokens] tokens · [tool_uses] calls · [duration]s
**Skills used**: comma-separated skill names from session telemetry
**Friction events**: count and categories (e.g., "2: escalation, retry") or "0 (clean)"
**File count**: N (from write_files) or "unknown"
**Complexity**: small | medium | large | unknown (1-2 files → small, 3-5 → medium, 6+ → large)
**Memory attributed**: OpenMemory queries that influenced this outcome, or "none"
**What worked / What failed**: brief
```

---

## 2026-03-04 -- story-430 -- Redesign Pokedex.tsx: make Collections visually exciting and self-explanatory
**Intent**: Replace plain Collections panel with vivid Discovery Archive — hero header, ghost empty state, card polish
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: ~2min
**Coder effort**: sonnet · 27692 tokens · 15 calls · 90.7s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Single-file surgical change; plan was precise with explicit class names and layout constraints; coder built clean on first pass
**What failed**: nothing

## 2026-03-04 -- story-428 -- invariant extraction from Fortran routines
**Intent**: Add structured invariants/constraints/error_codes fields to FortranRoutine, extract via regex from comment blocks, store in Pinecone metadata, inject into LLM context
**Result**: merged
**Agent**: arch
**Model**: sonnet
**Cycle time**: ~2.5h
**Coder effort**: sonnet · 39288 tokens · 29 calls · 146s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 4 (parser.py, ingest.py, prompts.ts, pinecone.ts)
**Complexity**: medium
**Memory attributed**: none
**What worked**: Clean execution, agent correctly added new dataclass fields and regex extraction
**What failed**: nothing

## 2026-03-04 -- story-442 -- Pokedex enhancements: sort, breakdown, New badge
**Intent**: Add sort toggle, LAPACK/BLAS breakdown bar, and "New" badge to Pokedex.tsx
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: ~2min
**Coder effort**: sonnet · 32801 tokens · 18 calls · 110.8s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Precise plan with exact JSX snippets and class names; coder matched exactly, no drift
**What failed**: nothing

## 2026-03-04 -- story-441 -- Archive button live count badge
**Intent**: Replace "Collection" button with "Archive · N found" badge so users understand before clicking
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: ~2min
**Coder effort**: sonnet · 34838 tokens · 19 calls · 85.8s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Single-file, precise plan with exact code snippet; coder matched exactly
**What failed**: nothing (pre-existing pinecone.ts build error unrelated)

## 2026-03-04 -- story-426 -- graph-expansion after embedding search
**Intent**: Add fetchRoutinesByNames with $in filter, parse comma-space dependencies, expand query context with structural neighbors
**Result**: merged
**Agent**: arch
**Model**: sonnet
**Cycle time**: ~1.6h
**Coder effort**: sonnet · 28703 tokens · 20 calls · 99s
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 3 (pinecone.ts, route.ts, config.ts)
**Complexity**: medium
**Memory attributed**: dependencies format (comma-space) confirmed from ingest.py read
**What worked**: Pre-flight read of ingest.py caught comma-space format; baked fix into coder prompt before agent ran
**What failed**: nothing

## 2026-03-04 -- story-427 -- cached derived facts from LLM responses
**Intent**: upsertSyntheticChunk with djb2 hash ID, after() for serverless-safe async upsert, stream buffering, includeSynthetic queryPinecone option
**Result**: merged (manual conflict resolution on route.ts)
**Agent**: arch
**Model**: sonnet
**Cycle time**: ~1.5h
**Coder effort**: sonnet · 33332 tokens · 21 calls · 94s
**Skills used**: run-stories, merge-worktree
**Friction events**: 1 (merge conflict — story-426 and story-427 both modified route.ts imports + allMatches variable)
**File count**: 2 (pinecone.ts, route.ts)
**Complexity**: small
**Memory attributed**: waitUntil/after() serverless pattern pre-identified; baked into coder prompt
**What worked**: Pre-identifying the serverless async issue prevented a silent bug; after() import resolved correctly
**What failed**: Route.ts merge conflict due to sequential stories both touching same file — resolved manually in 1 pass

## 2026-03-04 -- story-433 -- Zero matches guard
**Intent**: Return 404 when Pinecone returns no matches, skip LLM call
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: ~1h
**Coder effort**: sonnet · 23901 tokens · 17 calls · 58s
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean 5-line guard inserted at correct insertion point in route.ts
**What failed**: nothing

## 2026-03-04 -- story-437 -- Unicode/control character stripping
**Intent**: Extend sanitizeString to strip bidi overrides and ASCII control chars
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: ~1h
**Coder effort**: sonnet · 20340 tokens · 8 calls · 32s
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Combined character class replace, fastest batch-0 completion
**What failed**: nothing

## 2026-03-04 -- story-440 -- Prompt injection fence escape
**Intent**: Escape triple-backtick runs in m.text to prevent fence injection
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: ~1h
**Coder effort**: sonnet · 21134 tokens · 8 calls · 48s
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Zero-width space insertion between backtick groups — surgical 2-line change
**What failed**: nothing

## 2026-03-04 -- story-443 -- Archive button glow notification bubble
**Intent**: Replace static 'found' count in archive button with glowing notification bubble for new discoveries
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: ~1.9min
**Coder effort**: sonnet · 35944 tokens · 25 calls · 103s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 3
**Complexity**: medium
**Memory attributed**: none
**What worked**: Clean single-story execution; localStorage timestamp comparison pattern for unseen tracking; CSS keyframes glow animation with CSS variables
**What failed**: nothing

## 2026-03-04 -- story-448 -- Add outlined border to archive button
**Intent**: Change archive button default border from var(--ll-outline) to var(--ll-primary) so it reads as a button
**Result**: merged
**Agent**: qf
**Model**: sonnet
**Cycle time**: ~1min
**Coder effort**: sonnet · 21736 tokens · 15 calls · 45s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Single-line CSS swap, clean execution, no conflicts
**What failed**: nothing

## 2026-03-04 -- story-452 -- Make lens selection behave like analysis mode
**Intent**: Make lens selection behave like analysis mode — always one selected, clicking active does nothing instead of toggling off
**Result**: merged
**Agent**: qf
**Model**: sonnet
**Cycle time**: ~1h
**Coder effort**: not captured
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: clean execution — surgical change to onClick handler and type signatures
**What failed**: nothing

## 2026-03-04 -- story-455 -- Drill-down full file context
**Intent**: Add expand button to CodeSnippet to fetch and display full Fortran source file
**Result**: merged
**Agent**: arch
**Model**: sonnet
**Cycle time**: ~0.1h
**Coder effort**: sonnet · 32214 tokens · 23 calls · 124s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: GitHub raw fetch approach avoided Vercel filesystem limitation; clean execution
**What failed**: nothing

## 2026-03-04 -- story-456 -- README setup guide
**Intent**: Write README with deployed URL, env vars, local dev, and ingestion instructions
**Result**: merged
**Agent**: qf
**Model**: sonnet
**Cycle time**: ~0.1h
**Coder effort**: sonnet · 23236 tokens · 13 calls · 69s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Existing README had partial content; coder correctly updated to match spec
**What failed**: nothing

## 2026-03-04 -- story-461 -- Tooltip fix: HelpCircle icons in ModeSelector
**Intent**: Replace nonfunctional title-attribute tooltips on HelpCircle icons in ModeSelector with working custom CSS tooltip utility
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: ~0.7h
**Coder effort**: sonnet · 26377 tokens · 14 calls · 74s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: CSS `[data-tooltip]::after` pseudo-element approach using existing design tokens; Gemini analyze confirmed CSS globals approach over pure Tailwind for reusability across the codebase
**What failed**: nothing

## 2026-03-04 -- story-457 -- LAPACK Spellbook — Fantasy Adventure Game
**Intent**: DnD-style fantasy game with LAPACK routines as spells, 15 encounters, summary screen with Wizard Title
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: ~4h
**Coder effort**: sonnet · 51824 tokens · 23 calls · 231s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 3
**Complexity**: medium
**Memory attributed**: none
**What worked**: Clean single-story execution; coder correctly identified pre-existing build errors as out-of-scope; CSS keyframes for spell animations without adding framer-motion dependency
**What failed**: nothing

## 2026-03-04 -- story-465 -- Remove subroutine_name Pinecone filter
**Intent**: Remove nameTokens extraction and subroutine_name $in filter from route.ts; rely on HyDE for name-based retrieval
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: <1h
**Coder effort**: sonnet · 25937 tokens · 13 calls · 67s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Net -21 lines; pure deletion story with no new logic required; coder correctly preserved filtersApplied and category/data_type_prefix filters
**What failed**: nothing (preceded by story-464 badge change which surfaced that the filter was breaking caller queries)

## 2026-03-04 -- story-464 -- Direct match badge for exact name retrieval
**Intent**: Show 'Direct match' badge instead of cosine % score when subroutine_name exactly matches a query token
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: <1h
**Coder effort**: sonnet · 27502 tokens · 21 calls · 91s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: Gemini analyze caught case-insensitivity gap in original plan — plan was updated before coder launched, preventing a user-facing bug; clean execution
**What failed**: nothing

## 2026-03-04 -- story-463 -- Apply HyDE to name-filter queries
**Intent**: Remove nameTokens.length === 0 guard so HyDE runs for all queries including name-filter ones
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: <1h
**Coder effort**: sonnet · 24513 tokens · 14 calls · 55s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Surgical one-file change, plan was precise (exact line numbers + before/after), coder executed cleanly first pass
**What failed**: nothing
