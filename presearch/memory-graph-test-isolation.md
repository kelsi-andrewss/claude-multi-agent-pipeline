# Memory Graph Fix + Test-First Isolation + Compliance Pipeline

## Overview
Three interconnected pipeline improvements grounded in the principle that **behavior only changes when you change a tool, a prompt, or the model**:

1. **Memory graph**: Most surfaces are dead storage — data goes in, nothing reads it. Fix the read paths.
2. **Compliance pipeline**: The detection side works (corrections → auto-distill → behavioral-prefs.md). The compliance side doesn't — loading prefs into context is a suggestion, not enforcement. 42x corrections about "/ship" and 78x about "post-narration" prove the model sees prefs but doesn't reliably follow them. Fix: promote high-frequency corrections to **hooks** (structural enforcement), not just prose.
3. **Test-first isolation**: Launch test and code agents simultaneously from the same plan, in separate worktrees. Test agent never sees implementation. Tests validate spec compliance, not implementation correctness. This also serves as **deterministic backpressure** — tests are a hard gate, not advisory.

## Summary
The memory graph has 9 surfaces but only 3 close the write→read→behavior loop. The 3 that work (behavioral-prefs.md, corrections pipeline, OpenMemory) all feed PROMPT injection — but prompt injection is a suggestion, not enforcement. The 42x and 78x correction counts on basic routing/narration rules prove this. The fix isn't more context loading — it's structural enforcement via hooks and deterministic backpressure via build/test gates after each execution wave. Separately, test-first isolation decouples test writing from implementation, producing tests that validate the spec rather than rubber-stamping the code.

## Features
### MVP
0. Bootstrap: No scaffold — infrastructure changes to existing ~/.claude/ pipeline
1. **Compliance pipeline: prefs → hooks promotion** — When a behavioral pref hits 3+ corrections AND is structurally enforceable, auto-generate a hook that blocks the behavior. Detection works; add enforcement.
2. **Close dead memory loops** — Wire outcomes.md into plan critique, activate decision_preferences, remove dead surfaces
3. **Deterministic backpressure per wave** — Hard build+lint+typecheck gate after each execution wave in run-stories, not just at merge time
4. **Test-first parallel execution** — Launch test agent alongside code agent in run-stories Step 4, both working from plan file, test agent writes test files only
5. **Merge gate with test validation** — After both agents complete, run tests against real code, gate merge on pass
6. **Plan-as-contract enforcement** — Function signatures, acceptance criteria, test file targets in every plan

### Phase 2
7. **Auto-derive test_files from write_files** — Convention-based: `src/foo.ts` → `src/foo.test.ts`
8. **Signal processor fidelity** — Tighten decision-correlation threshold from 0.15 word overlap to embedding-based similarity
9. **Backpressure iteration loops** — When wave backpressure fails, auto-delegate fix to coder and re-run (up to 2 iterations)

### Cut
10. ~~Auto-learn patterns from coder failures~~ — Separate concern
11. ~~Collapse planning into single reviewable artifact~~ — Would require major pipeline restructure; current multi-file approach works if plan-as-contract is tightened

## Technical Research

### The Compliance Gap (from Reuben's analysis)

The memory system has a fundamental gap: **detection works, compliance doesn't**.

```
Detection pipeline (WORKS):
  transcript → stop hook → correction detection → correction_groups table
  → count >= 3 → auto-distill → behavioral-prefs.md → session context

Compliance pipeline (DOESN'T EXIST):
  behavioral-prefs.md → loaded into context → Claude reads it → ???

  42x corrections: "use /ship" — model still doesn't
  78x corrections: "don't narrate after /ship" — model still does
```

**Why prompt injection fails for compliance**: Claude processes behavioral-prefs.md as one of many context items. In a complex multi-tool interaction, the model's attention drifts from loaded preferences. Prose instructions compete with the immediate task. The model "knows" the preference but doesn't "enforce" it on itself.

**What works for compliance**: Hooks. `guard-direct-edit.sh` blocks direct file edits structurally — the model can't bypass it even if it "forgets." This is the only enforcement mechanism in the current system, and it works 100% of the time.

**The fix**: For each behavioral pref with 3+ corrections that describes a **structurally enforceable** behavior, generate a hook:

| Pref | Enforceable? | Hook design |
|------|-------------|-------------|
| "Use /ship for new work" | YES — detect when coder agents are launched without /ship | PostToolUse hook on Agent tool: if subagent_type in (quick-fixer, architect) and no active /ship skill invocation → block |
| "Don't narrate after /ship" | PARTIAL — can detect post-/ship text output but can't unsay it | Stop hook: detect narration after skill completion → log correction auto |
| "Log corrections before responding" | NO — ordering within a response isn't hookable | Keep as prompt, accept lower compliance |
| "Don't get stuck in PostToolUse loops" | YES — count consecutive PostToolUse events | PostToolUse hook: if same tool called 3x in a row with same args → warn |

**Not all prefs are hookable.** The promotion should evaluate:
1. Is the behavior detectable from tool call patterns or output structure?
2. Can a hook block or warn before the action completes?
3. Would blocking cause worse UX than the correction?

### Memory Graph Audit

**The Principle**: To change behavior, you must change a tool, a prompt, or the model. Storing data that nothing reads is waste.

| Surface | Writes | Reads | Behavior Change | Status |
|---------|--------|-------|-----------------|--------|
| behavioral-prefs.md | auto-distill + manual | session start mandatory pre-read | **PROMPT** — injected every session (but not enforced) | LIVE (weak) |
| corrections.md + correction_groups | manual + stop hook | auto-distill pipeline | **PROMPT** — promotes to behavioral-prefs.md after count >= 3 | LIVE (indirect) |
| OpenMemory | om_write gate + skills | session-start snapshot + on-demand | **PROMPT** — skill queries inject into coder prompts | LIVE (selective) |
| outcomes.md | merge-worktree Step 5.5 | nothing (mtime check only) | **NONE** — write-only audit log | DEAD |
| decision_preferences (epics.db) | signal_processor.py | nothing (pm_predict_preference uncalled) | **NONE** — signal accumulates, never read | DEAD |
| tool-learnings.md | manual + stop hook sync | OpenMemory sync only | **PARTIAL** — via OpenMemory indirectly | WEAK |
| om-ops.json | om_write gate | nothing | **NONE** — audit trail | DEAD (acceptable) |
| friction.json | (not written) | nothing | **NONE** — unimplemented | DEAD |
| skill-telemetry.jsonl | skill invocations | merge-worktree (skills_list) | **PROMPT** — cosmetic only | WEAK |

**Fixes by lever:**

| Surface | Fix | Lever |
|---|---|---|
| behavioral-prefs.md | Promote hookable prefs to actual hooks | **TOOL** (hook = tool) |
| outcomes.md | Read during plan critique: "last 5 stories with this agent: X% clean" | **PROMPT** |
| decision_preferences | Call pm_predict_preference in /draft-plan critique | **PROMPT** |
| friction.json | Remove dead references — correction pipeline covers this | Remove |
| OpenMemory snapshot | Elevate to mandatory pre-read block in load-session-context.sh | **PROMPT** |
| signal_processor | Tighten correlation threshold (0.15 → embedding similarity) | **TOOL** |

### Deterministic Backpressure

**Current**: Backpressure is advisory — LLM reviews LLM output. Build verification happens at merge time (merge-worktree Step 2.5), after all tokens are burned.

**Proposed**: Hard gates after each execution wave in run-stories.

```
Wave 0 (bootstrap stories) → build+lint gate → PASS → Wave 1
Wave 1 (feature stories batch 0) → build+lint gate → PASS → Wave 2
...
Final wave → build+lint+test gate → PASS → merge
```

**Implementation**: After each batch completes and merges into dev (run-stories Step 5c), before launching next batch:

```bash
cd <dev-branch-checkout>
# Detect and run project-appropriate checks
npm run build && npm run lint    # JS/TS
flutter analyze                   # Dart
cargo check && cargo clippy       # Rust
go build ./... && go vet ./...    # Go
python -m py_compile *.py         # Python (minimal)
```

This is already partially in Step 2c (post-bootstrap build verification) but only for bootstrap stories. Generalize it to every wave transition.

**Fail behavior**: If backpressure fails after wave N, the batch that just merged caused the failure. Re-delegate to the coder(s) from that batch with the error output. Up to 2 iterations per wave. If still failing after 2, mark remaining stories BLOCKED and stop.

### Test-First Isolation Architecture

**Current flow (sequential):**
```
Plan → Coder (worktree A) → Done → Unit-tester (same worktree A) → Tests → Merge
```
Problem: Unit-tester sees the implementation. Tests validate "code works as written" not "code satisfies spec."

**Proposed flow (parallel + isolated):**
```
Plan file (shared, read-only)
    ├── Coder agent (worktree A) → writes source files → pushes to story-branch
    └── Test agent (worktree B) → writes test files ONLY from acceptance criteria
                                                          ↓
                                              Merge gate: combine code+tests, run tests
                                                          ↓
                                              Pass → merge to dev
                                              Fail → re-delegate to coder (not test agent)
```

**This IS deterministic backpressure**: tests written from spec, not implementation, serve as an independent verification signal. If tests fail against the code, the code is wrong — not the tests.

**Key design decisions:**

1. **Same story-branch, sequential push**: Coder pushes first. Test agent fetches, merges locally, pushes. Simpler than separate branches.

2. **Write-target partitioning**: Coder owns `write_files` (source). Test agent owns `test_files` (test). Zero overlap.

3. **Test agent isolation — enforced structurally**:
   - Reads: plan file, acceptance criteria, shared type definitions (read-only context)
   - Does NOT read: source files, existing tests, coder's implementation
   - Writes: test files only
   - Does NOT run tests (no implementation exists yet)
   - Enforced: test agent worktree is created from dev branch BEFORE coder pushes — it literally can't see coder's code

4. **Merge gate validates integration**:
   - After both complete: combine code+tests in merged worktree
   - Run full test suite
   - Test compile error → re-delegate to test agent (wrong interface assumption)
   - Test logic failure → re-delegate to coder (implementation doesn't match spec)
   - Ambiguous → user decision

5. **Plan-as-contract** must include:
   - Function/class signatures with parameter types
   - Acceptance criteria as testable behavioral statements
   - Test file paths (explicit)
   - Import paths for shared interfaces

### Architecture

**Changes contained to:**
- `skills/run-stories/SKILL.md` — parallel launch, test_files conflict detection, per-wave backpressure
- `skills/merge-worktree/SKILL.md` — merge gate with test validation, failure attribution
- `skills/draft-plan/SKILL.md` — plan spec validation (signatures, acceptance criteria required)
- `ORCHESTRATION.md` — new sections: parallel testing, backpressure, compliance pipeline
- `mcp-servers/gemini/tools_pm_helpers.py` — test_files column migration
- `hooks/` — new compliance hooks generated from behavioral-prefs promotions
- `hooks/lib/signal_processor.py` — tighten correlation threshold
- `hooks/load-session-context.sh` — elevate OpenMemory snapshot to mandatory

**No new skills needed.**

### Patterns

- **Hook > Prose**: If a behavioral pref can be structurally enforced, make it a hook. Prefs that can't be hooked stay as prompt context but accept lower compliance rates.
- **Backpressure after every wave**: `build + lint + typecheck` is the minimum. Tests are the gold standard but require test infrastructure.
- **Test isolation**: Test agent NEVER reads source files. Worktree created before coder pushes.
- **Plan-as-contract**: Every plan includes function signatures and acceptance criteria. If missing, draft-plan critique rejects.
- **Failure attribution**: Test compile error → test agent. Logic failure → coder.

### Data Model

**stories table:**
```sql
ALTER TABLE stories ADD COLUMN test_files TEXT DEFAULT '[]';
```

**Hook generation** (new pattern): When auto-distill promotes a pref with count >= 3:
1. Evaluate if structurally enforceable (detectable from tool calls/output)
2. If yes: generate hook script in `hooks/compliance/`, register in settings
3. If no: keep as behavioral-prefs.md entry, log "not hookable: <reason>"

**signal_processor.py**: Replace word overlap (0.15 threshold) with embedding cosine similarity (0.6 threshold, same embeddings as OpenMemory dedup).

### Dependencies
- No new packages. All changes to pipeline skills, hooks, and DB schema.

### Gotchas

1. **Test agent needs type signatures**: Plan must include function signatures. Without them, test agent writes tests against imagined interfaces.
2. **Bootstrap stories skip test agent**: Can't write tests for scaffold/config. Skip test agent for bootstrap.
3. **Race condition on push**: Coder must push first. Enforce in test agent prompt + add retry with fetch if push rejected.
4. **Hook generation safety**: Auto-generated hooks could block legitimate actions. All generated hooks start as `warn` (log + continue), promoted to `block` only after manual review.
5. **Backpressure false positives**: Some warnings (unused variables from future-use code) aren't real failures. Backpressure should fail on errors only, warn on warnings.
6. **Signal processor migration**: Tightening threshold from 0.15 to 0.6 will break existing correlations. Run migration that recalculates all signal_scores with new threshold.

### Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Test agent writes untestable tests (wrong interfaces) | Med | High | Merge gate catches; plan-as-contract with signatures reduces |
| Auto-generated hooks block legitimate actions | High | Med | All hooks start as warn-only; manual promotion to block |
| Plan spec overhead slows planning phase | Med | Med | Only require signatures for stories with test_files; bootstrap exempt |
| Backpressure gate slows pipeline | Low | Med | Build/lint are fast (<30s); only blocks on real errors |
| Compliance hooks become stale | Med | Low | Hook health check in /skill-health; deprecate after 30 days without trigger |
| Double worktree overhead | Low | Low | Worktree creation is <1s; test agent uses Sonnet (fast) |

### Cost Estimate

**Development complexity:**
| Feature | Size | Notes |
|---------|------|-------|
| 1. Compliance pipeline (prefs → hooks) | M | auto-distill logic + hook generator + settings registration |
| 2. Close dead memory loops | M | load-session-context, draft-plan critique, ORCHESTRATION.md |
| 3. Per-wave backpressure | S | Generalize existing Step 2c to all wave transitions |
| 4. Test-first parallel execution | L | run-stories Steps 4+5 refactor, test agent prompt, DB migration |
| 5. Merge gate with test validation | M | merge-worktree refactor, failure attribution |
| 6. Plan-as-contract enforcement | S | draft-plan critique checklist, plan validation |

## Environment
- No new environment variables needed.

## Decisions
- **Compliance > context**: Hookable prefs become hooks (TOOL lever). Non-hookable prefs stay as prompt context (PROMPT lever). Accept that PROMPT lever has ~50-75% compliance.
- **Hook safety**: All auto-generated hooks start as warn-only. Manual review required to promote to block.
- **Test agent model**: Sonnet — test writing from acceptance criteria requires behavioral reasoning
- **Same branch strategy**: Coder and test agent push to same story-branch sequentially
- **Failure attribution**: Compile error → test agent, logic failure → coder
- **Backpressure scope**: build + lint + typecheck after every wave. Full test suite at merge gate only.
- **outcomes.md**: Wire into plan critique, not coder prompt — keeps coder prompts lean
- **friction.json**: Remove dead references — correction pipeline already captures friction
- **signal_processor threshold**: Migrate from 0.15 word overlap to 0.6 embedding similarity
- **om-ops.json**: Keep as audit trail — acceptable dead storage for debugging

## Constraints
- All changes to existing ~/.claude/ pipeline — no new projects or external services
- Must not break existing /ship → /run-stories → /merge-worktree flow for stories without test_files
- Test-first is opt-in per story (stories without test_files skip test agent launch)
- Every memory fix must trace to a specific tool/prompt/model lever — no "store and hope"
- Auto-generated hooks must not block without manual review

## Reference
- Reuben Brooks (C3): Feedback on memory system, backpressure principle, compliance gap analysis, hook-over-prose recommendation
- Don't Waste Your Backpressure (banay.me): deterministic feedback loops for agent quality
- Memory audit: hooks/load-session-context.sh, hooks/lib/om_write.py, hooks/lib/signal_processor.py
- Test isolation: current unit-tester behavior, run-stories Steps 4-5, merge-worktree Steps 2.5-3
- George (@odysseus0z): Linear→Ralph loop dispatch pattern — minimal orchestration with persistent state
- Karpathy: Async collaborative agent research — SETI@home model
- Beads/Gas Town: Wave-based task systems with backpressure
