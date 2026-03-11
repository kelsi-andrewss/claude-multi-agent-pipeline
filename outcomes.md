# Outcomes Log

Post-merge/rejection log for pattern recognition across sessions. Consulted on-demand, not loaded into every session.

## 2026-03-11 -- story-653 -- Update ORCHESTRATION.md §15 with phase-based delegation table
**Intent**: Replace §15 MCP context management with phase-based delegation model
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 25442 tokens · 15 calls · 74s
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Fast-path plan with exact task descriptions gave coder clear scope
**What failed**: nothing

## 2026-03-11 -- story-651 -- Merge-worktree phase delegation
**Intent**: Bundle git merges, cleanup, DB updates, outcome logging into one subagent per batch
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 36872 tokens · 16 calls · 91s
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file skill edit, plan was precise about insertion point and content
**What failed**: nothing

## 2026-03-11 -- story-652 -- Critique phase delegation
**Intent**: Bundle plan file reads, pm_critique, pm_add_decision into one subagent
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 54419 tokens · 23 calls · 137s
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Read-only context list in plan gave coder the reference patterns it needed
**What failed**: nothing

## 2026-03-11 -- story-646 -- Refactor presearch/SKILL.md into thin orchestrator
**Intent**: Replace monolithic presearch with thin orchestrator invoking /clarify → /research → /briefing
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 45721 tokens · 18 calls · 88s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file refactor. Coder reduced 318 lines to 118 lines. No escalation needed.
**What failed**: nothing

## 2026-03-11 -- story-647 -- Refactor ship/SKILL.md into thin orchestrator
**Intent**: Replace monolithic ship with thin orchestrator invoking child skills via Skill tool
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 67415 tokens · 22 calls · 165s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean refactor, 399 lines to 189 lines. All modes and flags preserved. No escalation.
**What failed**: nothing

## 2026-03-11 -- story-630 -- Compliance pipeline: prefs → hooks promotion
**Intent**: Auto-generate compliance hooks from high-frequency behavioral corrections
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.1h
**Coder effort**: sonnet · 56540 tokens · 31 calls · 203s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 3
**Complexity**: medium
**Memory attributed**: none
**What worked**: Clean execution, plan was precise enough for direct implementation
**What failed**: nothing

## 2026-03-11 -- story-631 -- Close dead memory loops
**Intent**: Wire outcomes.md into planning, activate decision_preferences, elevate OpenMemory snapshot
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.1h
**Coder effort**: sonnet · 67669 tokens · 27 calls · 195s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: Plan-writer caught friction.json was live (not dead as presearch claimed), avoided breakage
**What failed**: nothing

## 2026-03-11 -- story-632 -- Deterministic backpressure per wave
**Intent**: Hard build+lint+typecheck gate after each execution wave
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.1h
**Coder effort**: sonnet · 45784 tokens · 20 calls · 129s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean execution, single-file change layered cleanly on existing SKILL.md
**What failed**: nothing

## 2026-03-11 -- story-633 -- Test-first parallel execution
**Intent**: Dual coder+test agent launch, test_files DB column, merge gate
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.4h
**Coder effort**: sonnet · 75074 tokens · 41 calls · 1479s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 4
**Complexity**: medium
**Memory attributed**: none
**What worked**: Plan was self-contained enough that missing presearch file didn't matter
**What failed**: nothing

## 2026-03-11 -- story-634 -- Merge gate with test validation
**Intent**: Failure attribution, retry routing, test validation in merge-worktree
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.1h
**Coder effort**: sonnet · 55199 tokens · 25 calls · 226s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: Built cleanly on story-633's Step 5b skeleton, extended with full attribution logic
**What failed**: nothing

## 2026-03-11 -- story-635 -- Plan-as-contract enforcement
**Intent**: Add contract sections and critique gates to plan files for test-first isolation
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.1h
**Coder effort**: sonnet · 35087 tokens · 22 calls · 211s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean merge despite shared draft-plan SKILL.md with story-631 (different sections)
**What failed**: nothing

## 2026-03-09 -- story-594 -- /ship --quickfix mode
**Intent**: Add --quickfix flag to /ship that triggers lightweight path skipping Gemini and epics.db
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 35878 tokens · 22 calls · 111s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 2
**Complexity**: small
**Memory attributed**: pipeline redesign pattern (precise plan structure)
**What worked**: Clean single-pass execution. Well-specified plan with exact file targets enabled coder to execute without decisions.
**What failed**: nothing

## 2026-03-09 -- story-580 -- Fix auto-distillation duplicate spam in stop hook
**Intent**: Fix auto-distillation duplicate spam in stop hook
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: [sonnet] · 40912 tokens · 21 calls · 98s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file fix, exact code provided in plan, coder executed surgically
**What failed**: nothing

## 2026-03-08 -- story-570 -- Skill tracking chart integration tests
**Intent**: Verify chart data values, sorting, timeline aggregation, and success rate edge cases
**Result**: merged
**Agent**: unit-tester
**Model**: unknown
**Cycle time**: 0.0h
**Coder effort**: 39293 tokens · 15 calls · 99s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: pass (58/58)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-story execution, consolidated 4 overlapping stories into 1 to avoid write conflicts
**What failed**: nothing

## 2026-03-08 -- story-565 -- Dashboard Feature Additions
**Intent**: Dashboard Feature Additions
**Result**: merged
**Agent**: architect
**Model**: opus
**Cycle time**: 0.1h
**Coder effort**: opus · 65321 tokens · 46 calls · 235s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: pass (149 total: 100 existing + 49 new)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file execution, all 5 features implemented in one pass, 49 tests written and passing
**What failed**: nothing

## 2026-03-08 -- story-564 -- Test Coverage: All Tracking Write Paths
**Intent**: Add error-path and E2E tests for all 5 tracking write paths (write-turns, write-agent, backfill, patch-durations, parse_friction)
**Result**: merged
**Agent**: arch
**Model**: opus
**Cycle time**: 0.1h
**Coder effort**: opus · 73916 tokens · 44 calls · 329s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: pass (100/100)
**File count**: 5
**Complexity**: medium
**Memory attributed**: none
**What worked**: Clean execution. AST extraction solved backfill.py module-level import problem. HOME env override for patch-durations E2E tests. All 27 new tests passed first run.
**What failed**: nothing

## 2026-03-08 -- story-545 -- /smoke-test skill for plan-writer pipeline validation
**Intent**: Create /smoke-test skill that validates the /ship plan-writer pipeline end-to-end
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 42122 tokens · 21 calls · 128s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean execution from plan. Serialized after story-544 due to (unnecessary) dependency.
**What failed**: nothing

## 2026-03-08 -- story-544 -- Pytest unit tests for _apply_plan_to_story
**Intent**: Unit tests for DELETE-before-INSERT idempotency and state transition to ready
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 35344 tokens · 26 calls · 98s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: self (story IS the tests)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file test creation. Plan had exact function references and schema details.
**What failed**: nothing

## 2026-03-08 -- story-543 -- Background plan writers + task accumulation fixes
**Intent**: Move plan-file writing to parallel background agents, fix task accumulation bugs
**Result**: merged
**Agent**: architect
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 50600 tokens · 32 calls · 172s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 3
**Complexity**: medium
**Memory attributed**: none
**What worked**: Clean single-story execution from existing plan file. Execute mode in /ship skipped planning overhead.
**What failed**: nothing

## 2026-03-08 -- story-541 -- Documentation updates
**Intent**: Documentation updates
**Result**: merged
**Agent**: arch
**Model**: sonnet
**Cycle time**: 2.1h
**Coder effort**: sonnet · 68627 tokens · 56 calls · 7388s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 7
**Complexity**: large
**Memory attributed**: none
**What worked**: Clean execution — all 7 doc files updated, verification checks pass, disagreements.md reference correctly preserved in protocol section
**What failed**: nothing

## 2026-03-08 -- story-542 -- Tracking extensions (errors, skill metrics, OM health charts)
**Intent**: Tracking extensions (errors, skill metrics, OM health charts)
**Result**: merged
**Agent**: arch
**Model**: sonnet
**Cycle time**: 0.4h
**Coder effort**: not captured
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 1: blocked (background agent couldn't commit, main session committed from worktree)
**Tests**: skipped (no infra)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: Agent wrote code successfully; main session committed and pushed from worktree
**What failed**: Agent couldn't git commit (permission issue)

## 2026-03-08 -- story-540 -- Trim session start hook (load-session-context.sh)
**Intent**: Trim session start hook (load-session-context.sh)
**Result**: merged
**Agent**: arch
**Model**: sonnet
**Cycle time**: 0.2h
**Coder effort**: not captured
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 1: blocked (background agent couldn't write files, main session made targeted edits)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Two targeted edits (prune_expired + correction_groups simplification) instead of full rewrite — file was already partially trimmed by previous session
**What failed**: Background agent blocked by Write/Edit permissions

## 2026-03-08 -- story-539 -- Rewrite stop hook (session-learning-check.sh)
**Intent**: Rewrite stop hook (session-learning-check.sh)
**Result**: merged
**Agent**: arch
**Model**: sonnet
**Cycle time**: 0.3h
**Coder effort**: not captured
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 1: blocked (background agent couldn't write files, main session wrote via heredoc)
**Tests**: skipped (no infra)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Main session rewrote file via Bash heredoc after Write tool failed with "modified since read"
**What failed**: Background agent was blocked by Write/Edit permissions; Write tool failed twice with stale-read error

## 2026-03-08 -- story-537 -- Write gate + cleanup script
**Intent**: Write gate + cleanup script
**Result**: merged
**Agent**: arch
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: not captured
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 2
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean execution, both files created correctly
**What failed**: nothing

## 2026-03-08 -- story-538 -- Dead file cleanup + guard-direct-edit update
**Intent**: Dead file cleanup + guard-direct-edit update
**Result**: merged
**Agent**: qf
**Model**: haiku
**Cycle time**: 0.0h
**Coder effort**: not captured
**Skills used**: run-stories, merge-worktree
**Friction events**: 0 (clean)
**Tests**: skipped (no infra)
**File count**: 9
**Complexity**: large
**Memory attributed**: none
**What worked**: Deleted 7 files, cleaned tool-learnings.md, updated guard-direct-edit.sh allowlist
**What failed**: nothing

## 2026-03-06 -- story-523 -- Function-level write-target overlap detection
**Intent**: Add file:symbol syntax to run-stories conflict detection for function-level parallel safety
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 26415 tokens · 13 calls · 69s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: outcomes data (story-427 merge conflict drove this change)
**What worked**: Clean execution, coder inserted subsection and prompt update precisely
**What failed**: nothing

## 2026-03-06 -- story-522 -- Smoke test gate before merge
**Intent**: Add test step to merge-worktree between diff review and merge
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 30716 tokens · 23 calls · 105s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: outcomes data (28/31 stories skipped testing drove this change)
**What worked**: Clean execution, coder inserted Step 2.5 and updated outcome/report templates
**What failed**: nothing

## 2026-03-06 -- story-521 -- Default coders to Sonnet, Haiku only for truly trivial
**Intent**: Change ORCHESTRATION.md §2 coder default from Haiku to Sonnet with Haiku threshold rule
**Result**: merged
**Agent**: quick-fixer
**Model**: sonnet
**Cycle time**: 0.0h
**Coder effort**: sonnet · 25079 tokens · 16 calls · 74s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: outcomes data (Haiku 17% failure rate drove this change)
**What worked**: Clean execution, table replacement and threshold rule insertion precise
**What failed**: nothing

## 2026-03-06 -- story-520 -- Add one-time OpenMemory dedup cleanup script
**Intent**: Write cleanup script for duplicate OpenMemory entries
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: 0.0h
**Coder effort**: [haiku] · 22130 tokens · 14 calls · 77s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean execution, dry-run confirmed 44 duplicates found before any deletion
**What failed**: nothing

## 2026-03-06 -- story-518 -- Remove raw correction dual-write
**Intent**: Remove raw correction dual-write from session-learning-check.sh
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: 0.0h
**Coder effort**: [haiku] · 28725 tokens · 25 calls · 120s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean deletion — coder correctly identified that OM_DB variable needed to be preserved for transcript embedding section
**What failed**: nothing

## 2026-03-06 -- story-519 -- Add content-similarity dedup to transcript_embedder.py
**Intent**: Add content-similarity dedup to transcript_embedder.py
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: 0.0h
**Coder effort**: [haiku] · 26690 tokens · 17 calls · 70s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean execution, difflib similarity check added with single pre-loop query
**What failed**: nothing

## 2026-03-06 -- story-515 -- Normalize pm_dev_branch to always return dev
**Intent**: Change pm_dev_branch tool to use a single dev branch
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: 0.1h
**Coder effort**: haiku · 22769 tokens · 16 calls · 66s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: tool-learnings (pm_dev_branch prefix collision)
**What worked**: clean execution, surgical 2-line change
**What failed**: nothing

## 2026-03-06 -- story-516 -- Simplify merge-worktree to use single dev branch
**Intent**: Update merge-worktree skill to merge into dev
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: 0.1h
**Coder effort**: haiku · 31033 tokens · 24 calls · 131s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: clean execution, removed 18 lines of fallback logic
**What failed**: coder couldn't call pm_update_story (not available as deferred tool) — orchestrator handled state transition

## 2026-03-06 -- story-517 -- Simplify run-stories to use single dev branch
**Intent**: Update run-stories skill to use dev instead of per-epic branches
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: 0.1h
**Coder effort**: haiku · 31486 tokens · 22 calls · 111s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: clean execution, hardcoded dev branch regardless of pm_dev_branch return value
**What failed**: nothing

## 2026-03-05 -- story-510 -- Tag normalization for OpenMemory
**Intent**: Normalize tags in openmemory.sqlite to compact JSON, add normalization to transcript_embedder.py
**Result**: merged
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: ~2min
**Coder effort**: haiku · 59260 tokens · 30 calls · 130s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: tool-learning (Haiku regex replacement pattern)
**What worked**: Clean execution, coder correctly identified mcp.ts didn't need changes
**What failed**: nothing

## 2026-03-05 -- story-511 -- Decay in MCP mode
**Intent**: Add periodic decay scheduling to ai/mcp.ts
**Result**: merged (applied directly — file is gitignored)
**Agent**: quick-fixer (manual override — gitignored file)
**Model**: N/A (main session applied)
**Cycle time**: ~3min
**Coder effort**: haiku · 18512 tokens · 20 calls · 65s (BLOCKED, manual fix)
**Skills used**: ship, run-stories
**Friction events**: 1: blocked (gitignored write target)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Main session applied fix directly after coder blocked
**What failed**: Coder couldn't commit to gitignored file — plan should have flagged this

## 2026-03-05 -- story-512 -- Transcript quality improvement
**Intent**: Raise quality bar for transcript embedding
**Result**: merged (with post-merge fix)
**Agent**: quick-fixer
**Model**: haiku
**Cycle time**: ~1.5min
**Coder effort**: haiku · 29043 tokens · 18 calls · 90s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 1: restart (coder dropped original regex patterns)
**File count**: 1
**Complexity**: small
**Memory attributed**: tool-learning (Haiku regex replacement — 2nd occurrence)
**What worked**: is_repetitive filter and MIN_CONTENT_LENGTH change implemented correctly
**What failed**: Haiku replaced SYSTEM_MSG regex wholesale, dropping all 9 original patterns. Post-merge fixup required. This is the SECOND time this exact bug has occurred (tool-learnings.md).

## 2026-03-06 -- story-514 -- Add cycle_time parser normalization to skill-health Step 4
**Intent**: Add cycle_time parser normalization note to skill-health/SKILL.md Step 4
**Result**: merged
**Agent**: qf
**Model**: haiku
**Cycle time**: 0.0h
**Coder effort**: haiku · 25264 tokens · 18 calls · 71s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file edit. Haiku inserted normalization block at correct position in Step 4.
**What failed**: nothing

## 2026-03-06 -- story-513 -- Tighten merge-worktree cycle_time format
**Intent**: Tighten merge-worktree/SKILL.md cycle_time instruction to always use decimal hours
**Result**: merged
**Agent**: qf
**Model**: haiku
**Cycle time**: 0.0h
**Coder effort**: haiku · 26416 tokens · 12 calls · 51s
**Skills used**: ship, run-stories, merge-worktree
**Friction events**: 0 (clean)
**File count**: 1
**Complexity**: small
**Memory attributed**: none
**What worked**: Clean single-file edit. Haiku replaced the cycle_time instruction precisely.
**What failed**: nothing

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
