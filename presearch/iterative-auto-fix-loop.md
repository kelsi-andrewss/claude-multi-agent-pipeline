# Fix-Loop Skill for Claude Code

## Problem Statement
**What problem?** Coder agents generate code that passes the primary objective but often introduces secondary failures — lint warnings, type errors, failing tests, broken imports. The existing retry logic is fragmented: run-stories Step 5.0 handles build errors inline, Step 5b handles test failures separately, merge-worktree has its own escalation path, and none of them handle lint or visual regressions. When an agent hits an error, it reports it and stops. A human must re-run or manually fix.

**Why fix it?** Every manual re-prompt burns context, costs tokens, and breaks flow. The current inline Ralph Loop in run-stories only catches build errors — lint warnings and test failures slip through to merge, where they're harder to fix. Stories that could self-heal in 2-3 iterations instead require human intervention.

**Why integral?** The orchestration system's value proposition is autonomous shipping — `/ship` through to merged code. A missing fix loop is the gap between "code generated" and "code ready to merge." Without it, every story is one lint error away from requiring human babysitting, undermining the entire pipeline's autonomy.

**End goal:** A coder agent produces code with compile errors, lint warnings, or failing tests. The fix-loop skill detects all issues via a hierarchical validation pyramid, fixes them iteratively with model escalation, and terminates only when every validation layer passes clean. The human sees a merged story, not a list of errors to fix manually.

## Overview
The /fix-loop skill is a standalone orchestrator for the detect-diagnose-fix-revalidate cycle. It extracts and unifies the inline retry logic currently scattered across run-stories (Step 5.0 Ralph Loop, Step 5b merge gate retry) into a single reusable skill callable by humans via `/fix-loop` and programmatically by `/run-stories`, `/ship`, and `/quickfix`.

The skill implements a strictly gated validation pyramid (compile → lint → types → tests), fixing issues at each layer before proceeding to the next. It uses SHA-256 error hashing for oscillation detection, atomic git commits for rollback, and adaptive model escalation (Sonnet → Opus) when fixes stall. A hard iteration cap prevents runaway costs.

## Summary
Fix-loop unifies scattered retry logic (run-stories Step 5.0, Step 5b, merge-worktree escalation) into one reusable skill. Implements a strictly gated validation pyramid: compile errors must be fixed before lint runs, lint must pass before tests run. Each successful layer is git-committed for granular rollback. Anti-oscillation via SHA-256 error hashing and error count delta tracking. Adaptive model escalation — starts Sonnet, escalates to Opus after 3 stalled iterations. Hard cap at 10 iterations. Runs inside existing worktrees (never creates its own). Validation-runner.sh script handles project-type detection and error normalization. Targeted validation during loop, full suite at termination gate. Returns DONE/NEED_DECISION/BLOCKED per subagent contract. Replaces inline Ralph Loop in run-stories, making the same fix logic available to /quickfix and standalone use.

## Features

### MVP
1. **Fix-loop SKILL.md** — Core orchestration skill with YAML frontmatter. Implements the detect→diagnose→fix→revalidate loop with strictly gated validation pyramid. Args: `--worktree-path` (required), `--max-retries` (default 3, max 10), `--skip-visual` (default true for MVP). Handles: compile errors, lint warnings, test failures. Tracks iteration state (error hashes, error counts, consecutive no-progress). Model escalation after 3 stalled iterations. Atomic git commits per layer pass. Returns DONE/NEED_DECISION/BLOCKED.
   - Create: `skills/fix-loop/SKILL.md`

2. **Validation runner script** — Shell script implementing the validation pyramid. Detects project type (Flutter/Node/Python/Rust/Go via filesystem markers), runs appropriate compile/lint/test commands, returns unified JSON with per-layer results. Wraps existing build-verify.sh for compile step, adds lint and test layers.
   - Create: `scripts/validation-runner.sh`

3. **Run-stories integration** — Update run-stories Step 5.0 to delegate to `/fix-loop` instead of inline Ralph Loop. Step 5b test retry delegates to fix-loop with `--skip-compile` (already passed). Preserves existing circuit breaker thresholds as defaults.
   - Modify: `skills/run-stories/SKILL.md`

### Phase 2
4. **Visual regression detection** — Screenshot capture via platform-appropriate tool (e.g., `flutter test --update-goldens` for Flutter, headless Chrome for web), comparison via pixelmatch/SSIM, semantic diff conversion for LLM consumption. Entirely greenfield — no existing infrastructure.
   - Reason for deferral: no existing screenshot tooling, comparison infrastructure, or diff-to-text pipeline exists in the codebase

5. **Counterexample injection** — Track failed fix attempts as negative examples, inject into subsequent prompts ("do not generate patches similar to: ..."). Research shows PatchAgent uses this pattern effectively.
   - Reason for deferral: requires structured patch history storage and prompt engineering iteration

6. **Adaptive convergence detection** — Replace fixed iteration limits with dynamic progress measurement (error count trending, fix novelty scoring). No production system implements this yet per research.
   - Reason for deferral: research gap — no proven implementation exists to reference

## Technical Research

### Architecture
```
/fix-loop invocation
    │
    ├── Validation Runner (scripts/validation-runner.sh)
    │   ├── Layer 1: Compile (wraps build-verify.sh)
    │   ├── Layer 2: Lint (project-type detection → appropriate linter)
    │   ├── Layer 3: Tests (project-type detection → test runner)
    │   └── Returns: unified JSON with per-layer pass/fail + error output
    │
    ├── State Tracking (run-state.db)
    │   ├── error_hash (SHA-256 of combined error output)
    │   ├── error_count per layer
    │   ├── consecutive_no_progress counter
    │   └── iteration_number
    │
    ├── Fix Agent (coder subagent in worktree)
    │   ├── Receives: error output + affected files + fix history
    │   ├── Model: Sonnet (default), Opus (after 3 stalls)
    │   └── Returns: DONE/NEED_DECISION/BLOCKED
    │
    └── Git Checkpointing
        ├── Commit after each layer passes
        ├── Rollback to last checkpoint if next layer fails
        └── Final full-suite validation before DONE
```

**Integration points:**
- `/run-stories` Step 5.0 → delegates to `/fix-loop` instead of inline Ralph Loop
- `/ship` → transitively via run-stories
- `/quickfix` Step 7 → can invoke `/fix-loop` for post-coder validation
- `/merge-worktree` → fix-loop runs before merge gate, not after

### Patterns
- **Error normalization**: All validation failures normalized to JSON: `{layer, tool, message, file, line, column}`. Validation-runner.sh handles the conversion from raw compiler/linter/test output.
- **State hashing**: SHA-256 of combined error output per iteration. Matches existing Ralph Loop pattern in run-stories Step 5.0.
- **Git atomicity**: `git add <changed-files> && git commit -m "fix-loop: <layer> clean (iteration N)"` after each layer passes. Never `git add -A`.
- **Model escalation**: Sonnet for iterations 1-3. If error hash unchanged for 3 consecutive iterations OR error count increases, escalate to Opus. Matches ORCHESTRATION.md §2 escalation rules.
- **Subagent contract**: Fix agents return DONE/NEED_DECISION/BLOCKED per ORCHESTRATION.md §15. Fix-loop itself returns the same contract to its caller.
- **Policy-mechanism split**: Orchestration logic in SKILL.md, detection/verification in scripts/validation-runner.sh (per decision-78).

### Dependencies
- `scripts/build-verify.sh` — existing compilation verification (may need creation if not yet implemented)
- `scripts/validation-runner.sh` — new script wrapping build-verify.sh + lint + test
- `run-state.db` — existing transient state database (per decision-76)

### Gotchas
- **build-verify.sh may not exist yet** — scout notes referenced scripts may not all be implemented. Must verify existence and create stub if missing.
- **Ralph Loop plugin interference** — the installed Ralph Loop plugin fires on Stop hook in every session. Fix-loop must either coordinate with it or the plugin should be disabled when fix-loop is active.
- **Context window exhaustion** — feeding full test output into the LLM on each iteration can exhaust context. Truncate error output to last 100 lines per layer.
- **Flaky tests** — no existing pattern handles non-deterministic test failures. MVP treats flaky tests as real failures; Phase 2 could add flaky detection via multiple runs.
- **Project-type detection** — validation-runner.sh must detect project type from filesystem markers. Current build-verify.sh does this for compilation only; lint and test commands vary by project type.

### Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Infinite loop if circuit breakers fail | High | Low | Hard cap at 10 iterations + error hash detection + consecutive no-progress limit |
| Fix-loop falsely reports DONE despite failing builds | High | Low | Final full-suite validation gate before reporting DONE |
| Context exhaustion during long fix sessions | Med | Med | Truncate error output to 100 lines, reset context between iterations |
| Opus cost escalation on stubborn errors | Med | Med | Max 3 Opus iterations, then BLOCKED. Hard budget cap. |
| Ralph Loop plugin conflict | Med | High | Document deconfliction strategy; consider disabling plugin during fix-loop |
| build-verify.sh doesn't exist yet | Med | Med | Verify existence at skill start; create stub or error with actionable message |

## Test Strategy

### Critical paths
- Fix-loop SKILL.md follows established frontmatter pattern (name, description, args)
- Uses build-verify.sh for compilation detection, not reimplementing project-type detection
- Circuit breakers match or extend Ralph Loop thresholds (max 3 retries default, configurable to 10)
- Coder agents receive standard tool constraint block (no mcp__gemini__*, no pm_* except pm_update_story)
- Does not use EnterWorktree from the main session
- Returns DONE/NEED_DECISION/BLOCKED conforming to ORCHESTRATION §15
- Tracks error hash for oscillation detection using SHA-256
- Validation pyramid ordering enforced: compile → lint → tests
- Does not duplicate Ralph Loop plugin functionality — replaces inline Step 5.0

### Edge cases
- Iteration cap reached without zero issues → returns NEED_DECISION with remaining errors
- Same error hash 3 consecutive times → model escalation triggers
- Error count increases after fix → rollback to last checkpoint, try different approach
- No errors found on first run → returns DONE immediately (no iterations needed)
- build-verify.sh missing → actionable error, not silent failure

### Integration boundaries
- build-verify.sh JSON output contract (fix-loop depends on same schema)
- Subagent return contract: DONE/NEED_DECISION/BLOCKED
- run-state.db schema (fix_loop_state table: iteration, error_hash, error_count, model, worktree_path)
- Run-stories Step 5.0 delegation (fix-loop must accept same args Ralph Loop currently uses)

### What NOT to test
- YAML frontmatter parsing — Claude Code handles this
- Git commit mechanics — git is reliable
- Project-type detection in isolation — test via /smoke-test end-to-end

## Blast Radius
- **skills/run-stories/SKILL.md**: Step 5.0 changes from inline Ralph Loop to `/fix-loop` delegation. Step 5b test retry also delegates. This is the highest-risk change — run-stories is the most-used skill. Confidence: exhaustive (scout mapped all 5 retry patterns).
- **skills/ship/SKILL.md**: Transitively affected via run-stories. No direct changes needed.
- **skills/quickfix/SKILL.md**: Step 7 coder launch can optionally invoke `/fix-loop` for post-coder validation. Low risk — additive, not replacing.
- **ORCHESTRATION.md**: §8 (Merge & Escalation) may need update if fix-loop changes escalation semantics. Review needed.
- **settings.json**: May need permission entry if fix-loop uses new hook scripts.
- **Runtime contracts**: build-verify.sh JSON schema, subagent DONE/NEED_DECISION/BLOCKED, run-state.db schema.
- **Failure symptoms**: (1) infinite loops if circuit breakers fail, (2) stories marked DONE despite failing builds, (3) context exhaustion if error output not truncated, (4) merge queue stalls if fix-loop holds story indefinitely.

## Success Criteria
- A coder agent produces code with 3 lint warnings and 1 test failure. Fix-loop resolves all 4 issues autonomously without human intervention. The story merges clean.
- Run-stories Step 5.0 delegates to `/fix-loop` and produces identical behavior to the current inline Ralph Loop for build-error-only cases (backward compatibility).
- `/fix-loop` is callable standalone: `claude -p "/fix-loop --worktree-path /path/to/worktree"` runs headlessly and returns structured output.
- Oscillation detection works: when the same error hash appears 3 times, the loop escalates model rather than retrying with the same approach.
- The fix-loop terminates in under 10 iterations for 95%+ of cases (measured after 20+ invocations).

## Decisions
- **Standalone skill over stop-hook re-injection** — Fix-loop needs multi-phase validation (compile→lint→tests), which requires different commands at each phase. Stop-hook re-injection only supports "re-run the same prompt." (scout conflict resolution)
- **Unify scattered retry logic** — Extract inline retry from run-stories Step 5.0 and Step 5b into standalone `/fix-loop`. Makes the same logic available to /quickfix and standalone invocation. (scout conflict resolution, research recommendation)
- **3 retries default, configurable to 10** — Matches existing Ralph Loop thresholds. Configurable via --max-retries for callers that need more budget. (scout conflict resolution)
- **Adaptive model escalation** — Sonnet→Opus after 3 stalled iterations. Follows ORCHESTRATION.md §2 escalation pattern. (user decision)
- **Atomic git commits per layer** — Compile clean→commit, lint clean→commit, tests pass→commit. Enables granular rollback. (user decision)
- **Hybrid validation scope** — Targeted during loop, full suite at termination. Balances speed with correctness. (user decision)
- **Strictly gated validation pyramid** — Each layer must pass before proceeding to next. (user decision)
- **Transient state in run-state.db** — Per decision-76: iteration state (error hashes, counts) goes to run-state.db, not epics.db.
- **Visual regression deferred to Phase 2** — No existing infrastructure; entirely greenfield. MVP covers compile, lint, and test only.

## Constraints
- Claude Code orchestration project — skills are SKILL.md with YAML frontmatter, shell/python/markdown
- Main session cannot use EnterWorktree — fix-loop operates on existing worktrees passed via --worktree-path
- Coder agents must not call mcp__gemini__* tools
- Subagent return contract: DONE/NEED_DECISION/BLOCKED (ORCHESTRATION §15)
- Trust-informed model selection governed by ORCHESTRATION.md §2
- Policy-mechanism split: scripts in scripts/, orchestration in SKILL.md (decision-78)
- Out of scope: performance profiling, security scanning, CI/CD deployment

## Reference
- [How the agent loop works — Anthropic Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/agent-loop)
- [SWE-agent: Agent-Computer Interfaces — NeurIPS 2024](https://arxiv.org/abs/2405.15793)
- [Aider lint/test auto-fix](https://aider.chat/docs/usage/lint-test.html)
- [RepairAgent: Autonomous LLM-Based Agent for Program Repair](https://arxiv.org/html/2403.17134v1)
- [Self-Improving Coding Agents — Addy Osmani](https://addyosmani.com/blog/self-improving-agents/)
- [Spotify Honk: Background Coding Agents Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- [SWE-agent Competitive Runs: cost limits](https://swe-agent.com/latest/usage/competitive_runs/)
- [ESLint --fix cycling detection via state hashing](https://eslint.org/docs/latest/use/command-line-interface#--fix)
- [Best Practices for Claude Code — screenshots as verification](https://code.claude.com/docs/en/best-practices)
