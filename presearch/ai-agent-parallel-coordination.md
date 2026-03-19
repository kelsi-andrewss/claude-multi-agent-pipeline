# Parallel Orchestration & Autonomous Reliability

## Problem Statement
**What problem?** Epic-level serialization limits throughput. Stories run in parallel within an epic but epics are sequential. Sequential merging into dev is the actual ceiling. No agent health monitoring means stuck coders block indefinitely. No auto-review loops means human review of every merge. Conflict detection (pm_check_conflicts) is untested at scale and has no dependency-level analysis.

**Why fix it?** Can't scale beyond 3-5 concurrent stories. The system works but doesn't compound efficiency gains as project complexity grows. A single stuck Haiku agent can block the pipeline for hours with no detection. Every merge requires manual approval even for trivial changes.

**Why integral?** The orchestration system's value proposition is that it multiplies developer output. If throughput doesn't scale with project complexity, the system becomes a bottleneck rather than a multiplier. Cross-epic parallelism, smart merging, and graduated autonomy are the difference between a task runner and a production-grade agent factory.

**End goal:** Run 10+ concurrent stories across multiple epics, with automatic conflict detection, health monitoring, self-correcting review loops, and measurable trust-based autonomy that reduces human intervention for proven-reliable work.

## Overview
This upgrade transforms the orchestration layer from epic-serial execution to cross-epic parallel execution with three supporting systems: a smart merge queue that handles concurrent integrations, a dual-gate health monitor that catches stuck agents, and a graduated autonomy system that earns trust through measured performance. The Ralph Loop pattern provides self-correcting review cycles, and outcomes feedback closes the learning loop from write-only logging to automated decision input.

## Summary
Upgrade the dotclaude orchestration pipeline to support cross-epic story parallelism by removing epic-level serialization and implementing a priority merge queue with dependency locking. Add a dual-gate agent health monitor (pattern detection + resource limits) via run-state.db extensions. Integrate Ralph Loop auto-review with circuit breakers into the coder pipeline. Build graduated autonomy with a layered trust system (global baseline + domain-scoped overrides on divergence). Close the outcomes feedback loop so merge history informs model selection and autonomy gates. All changes stay within Claude Code primitives (skills, hooks, scripts) and extend existing state stores (epics.db, run-state.db, OpenMemory). Key decisions: hybrid conflict detection (git merge-tree + semantic escalation), priority queue with dependency locking, and MemRL-inspired outcome-based learning on the existing signal processor.

## Features

### MVP (Phase 1 — High-Throughput Core)

1. **Cross-epic story parallelism** — Remove epic-level serialization from run-stories. Stories from different epics execute concurrently. pm_check_conflicts checks write-targets across ALL in-progress stories, not just same-epic. Epics remain grouping only.
   - `skills/run-stories/SKILL.md` (remove epic-serial assumption)
   - `ORCHESTRATION.md` Section 3, 7, 8 (parallel workflow rules)
   - Size: **M**

2. **Smart merge queue** — Replace sequential batch merge with a priority queue. Stories merge as soon as tests pass IF no write-target overlap with stories ahead in queue. Non-conflicting stories skip the queue. Queue state tracked in run-state.db.
   - `skills/merge-worktree/SKILL.md` (queue logic)
   - `.claude/scripts/merge-queue.py` (new — mechanism script per decision-78)
   - `.claude/scripts/init-run-db.py` (add merge_queue table)
   - Size: **L**

3. **Hybrid conflict detection** — Two-tier pre-merge check. Tier 1: git merge-tree simulation (fast, language-agnostic). Tier 2: if Tier 1 detects conflict, semantic check via symbol-level analysis to filter false positives from textual proximity. Extends pm_check_conflicts with merge simulation.
   - `skills/run-stories/SKILL.md` Step 2b (add merge-tree check)
   - `.claude/scripts/conflict-check.sh` (new — wraps git merge-tree)
   - Size: **M**

### Phase 2 — Reliability & Feedback Loops

4. **Dual-gate agent health monitor** — Background watchdog for coder agents. Gate 1: pattern detection (same tool call repeated N times, oscillating edits). Gate 2: soft resource budget (token count, elapsed time). Extends run-state.db with heartbeat timestamps and tool call hashes. Watchdog runs as a cron-like check during run-stories execution.
   - `.claude/scripts/agent-watchdog.py` (new — mechanism script)
   - `.claude/scripts/init-run-db.py` (add agent_heartbeats table)
   - `skills/run-stories/SKILL.md` (launch watchdog, handle stuck detection)
   - Size: **M**

5. **Ralph Loop auto-review integration** — Wire the installed ralph-loop plugin into the coder pipeline. After coder completes, run lint + test. If failures detected, re-inject with error context for up to 3 self-correction attempts. Circuit breakers: CB_NO_PROGRESS_THRESHOLD=3, CB_SAME_ERROR_THRESHOLD=5. Dual-exit-gate: completion indicators + explicit EXIT_SIGNAL.
   - `skills/run-stories/SKILL.md` Step 5 (add review loop before merge)
   - `settings.json` (ralph-loop configuration)
   - Size: **M**

6. **Outcomes feedback loop** — Transform outcomes.md from write-only to structured input. Parse outcomes into merge_outcomes table in run-state.db. Feed success rates, cycle times, and failure patterns into signal_processor for decision weight updates.
   - `.claude/scripts/outcomes-parser.py` (new — extract structured data)
   - `.claude/scripts/init-run-db.py` (add merge_outcomes table)
   - `hooks/lib/signal_processor.py` (consume merge_outcomes for scoring)
   - Size: **M**

### Phase 3 — Intelligence & Trust

7. **Graduated autonomy (trust calibration)** — Layered trust system. Global trust score = aggregate success rate across all merge_outcomes. Domain-scoped overrides auto-created when divergence detected (3+ domain failures while global is green). Domain tags derived from write-target paths. Graduation gates check min(global, domain). Feeds into model selection (replace rule-based escalation) and approval requirements (auto-approve for high-trust domains).
   - `hooks/lib/signal_processor.py` (trust score calculation)
   - `hooks/load-session-context.sh` (inject trust scores at session start)
   - `ORCHESTRATION.md` Section 2 (model selection from trust scores)
   - `refs/orch-memory.md` (document trust calibration)
   - Size: **L**

## Technical Research

### Architecture
- **Hierarchical planner-worker-judge** (validated by CooperBench + Cursor): main session plans, coders execute, reviewers judge. No peer-to-peer coordination between workers. [Source: CooperBench, arxiv.org/html/2601.13295v1]
- **Explicit messaging over stigmergy**: production systems use SQLite mail (Overstory) or event streams (OpenHands), not environment-based indirect communication. [Source: Overstory, github.com/jayminwest/overstory]
- **Priority queue with dependency locking**: Overstory's FIFO queue + Auto Claude's 3-tier resolution inform the design, adapted to our write-target tracking. [Source: Overstory, Auto Claude]

### Patterns
- **Conflict detection**: hybrid git merge-tree + semantic escalation. Informed by Grove's 5-layer approach but without AST parser dependency. [Source: Grove, github.com/NathanDrake2406/grove]
- **Health monitoring**: dual-gate (pattern + resource) from Ralph Loop circuit breakers + OpenHands stuck detection. [Source: ralph-claude-code, OpenHands SDK V1]
- **Trust calibration**: MemRL-inspired outcome-based scoring. Freeze the model, score the outcomes, adjust autonomy. Global baseline + domain overrides like our correction→preference pipeline. [Source: MemRL, arxiv.org/html/2601.03192v2]
- **Auto-review**: Ralph Loop stop hook re-injection with dual-exit-gate. Bounded iterations prevent overbaking. [Source: ralph-claude-code, BugBot]

### Shared Interfaces

**merge_outcomes table** (run-state.db) — consumed by features 6, 7:
```sql
CREATE TABLE merge_outcomes (
  id INTEGER PRIMARY KEY,
  story_id TEXT NOT NULL,
  epic_id TEXT,
  agent TEXT,           -- quick-fixer | architect
  model TEXT,           -- haiku | sonnet | opus
  domain_tags TEXT,     -- JSON array derived from write-target paths
  predicted_conflict BOOLEAN,
  actual_conflict BOOLEAN,
  success BOOLEAN,      -- clean merge with passing tests
  cycle_time_s INTEGER,
  revert_count INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
```

**merge_queue table** (run-state.db) — consumed by feature 2:
```sql
CREATE TABLE merge_queue (
  id INTEGER PRIMARY KEY,
  story_id TEXT NOT NULL,
  priority INTEGER DEFAULT 0,  -- higher = merge first
  write_targets TEXT,           -- JSON array of file paths
  status TEXT DEFAULT 'queued', -- queued | merging | merged | blocked
  queued_at TEXT DEFAULT (datetime('now')),
  merged_at TEXT
);
```

**agent_heartbeats table** (run-state.db) — consumed by feature 4:
```sql
CREATE TABLE agent_heartbeats (
  id INTEGER PRIMARY KEY,
  story_id TEXT NOT NULL,
  agent_id TEXT,
  last_tool_call TEXT,       -- tool name
  tool_call_hash TEXT,       -- hash of tool name + args for repetition detection
  repeat_count INTEGER DEFAULT 0,
  token_estimate INTEGER DEFAULT 0,
  last_heartbeat TEXT DEFAULT (datetime('now'))
);
```

**trust_scores** (computed, not stored — derived from merge_outcomes):
- `global_score` = success_count / total_count across all outcomes
- `domain_score(tag)` = success_count / total_count filtered by domain_tag
- Domain override created when: domain_score < global_score - 0.15 AND domain_count >= 3
- Graduation gate: min(global_score, domain_score) >= threshold (default 0.85 for auto-approve, 0.70 for reduced review)

### Dependencies
- `git merge-tree` — built into git, no external dependency
- Existing: Ollama nomic-embed-text, epics.db, OpenMemory, run-state.db
- Ralph Loop plugin — already installed, needs configuration wiring

### Gotchas
- **Semantic conflicts remain unsolved**: git merge-tree + symbol analysis catches textual and structural conflicts, but two stories making incompatible assumptions about a shared API will merge cleanly and fail at runtime. Mitigation: build-verify.sh runs tests post-merge. [Source: CooperBench]
- **Overbaking phenomenon**: Ralph Loop iterations without tight scope produce bizarre emergent behavior. Mitigation: CB_NO_PROGRESS_THRESHOLD=3, bounded to 3 retry iterations max. [Source: Ralph Loop research]
- **SQLite WAL concurrency**: multiple parallel agents writing to run-state.db simultaneously. Mitigation: WAL mode + busy_timeout(5000) + retry logic in scripts.
- **ORCHESTRATION.md section renumbering**: other skills reference sections by number. Adding new sections or reordering breaks references. Mitigation: add new sections at the end (Section 16+), don't renumber existing.
- **Rate limits**: 10+ parallel agents hit API rate limits. Mitigation: run-stories already staggers launches. Add explicit concurrency cap in run-state.db.

### Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Dependency deadlock in merge queue (A waits for B, B waits for A) | High | Low | Force-sequential fallback when circular dependency detected |
| Stuck watchdog kills a valid long-running architect task | Med | Med | Architect tasks get 3x the soft budget; pattern detection distinguishes progress from loops |
| Trust score gaming (easy tasks inflate domain scores) | Med | Low | Weight by story complexity (from plan file) not just count |
| Semantic conflicts slip through hybrid detection | High | Med | build-verify.sh + test suite is the safety net; track false-negative rate in merge_outcomes |
| Ralph Loop infinite cost burn | High | Low | MAX_CALLS_PER_HOUR=100 + hard kill after 3 retries |

## Test Strategy

### Critical paths
- run-stories launches stories from 2+ epics simultaneously without blocking
- merge queue allows non-conflicting story to merge ahead of conflicting one
- hybrid conflict detection catches overlapping write targets and passes non-overlapping same-file edits
- agent watchdog detects stuck agent (repeated tool call) within 2 minutes
- Ralph Loop retries on test failure and exits on 3rd consecutive no-progress
- trust score correctly downgrades domain after 3 failures
- outcomes parser extracts structured data matching merge_outcomes schema

### Edge cases
- Two stories editing different functions in the same file: hybrid detection must allow this
- Merge queue with single story: degenerates to current sequential behavior (no regression)
- Watchdog kills agent mid-write: worktree must be in clean state (git stash or revert)
- Trust score with zero history: defaults to current rule-based behavior (no regression)
- Ralph Loop on a story with no tests: circuit breaker fires immediately (nothing to retry)

### Integration boundaries
- run-state.db schema changes must be backward-compatible (init-run-db.py handles migration)
- signal_processor.py API: trust_score() must return float [0,1] consumable by ORCHESTRATION rules
- merge-queue.py must work with existing merge-worktree git operations
- agent-watchdog.py must not interfere with Claude Code's internal agent management

### What NOT to test
- git merge-tree behavior (git's responsibility)
- Claude Code agent timeout internals (not our code)
- Existing correction→preference pipeline (tested by usage, don't regression-test the learning system)

## Blast Radius

- **ORCHESTRATION.md**: loaded by every skill at session start. 6+ skills reference sections by number. New content MUST be additive (new sections at end). Confidence: exhaustive.
- **run-stories/SKILL.md**: invoked by /ship, referenced by ORCHESTRATION.md, calls merge-worktree. Change to launch logic affects all story execution. Confidence: exhaustive.
- **merge-worktree/SKILL.md**: invoked by run-stories and directly. Change to merge logic affects all code integration. Confidence: exhaustive.
- **signal_processor.py**: imported by stop_processor.py. All correction detection and decision scoring flows through it. Confidence: exhaustive.
- **init-run-db.py**: schema changes affect all run-state.db consumers. Must handle migration from existing schema. Confidence: exhaustive.
- **Blind spots**: pm_check_conflicts implementation is server-side in Gemini MCP (not fully inspectable). Claude Code internal agent timeout behavior is not configurable from skill definitions.

## Success Criteria
- **Concurrency**: stable execution of 10+ concurrent stories across 3+ epics without manual intervention
- **Merge throughput**: non-conflicting stories merge without waiting for conflicting stories ahead of them
- **Health detection**: stuck agent detected and reported within 2 minutes of entering a loop
- **Self-correction**: Ralph Loop fixes at least 30% of lint/test failures without human intervention
- **Trust graduation**: after 10 clean merges in a domain, that domain's approval requirements are automatically relaxed
- **Zero regression**: existing single-epic workflows work identically (merge queue degenerates to sequential)

## Decisions
- **Conflict detection**: Hybrid (git merge-tree + semantic escalation) — balances speed with precision without requiring AST parsers (user decision)
- **Merge queue**: Priority queue with dependency locking — non-conflicting stories skip queue (user decision)
- **Agent health**: Dual-gate monitor (pattern detection + soft resource limits) — catches loops without killing valid long tasks (user decision)
- **Autonomy scope**: Layered global + domain overrides on divergence — like correction→preference, only create domain scores when data demands it (user decision)
- **Auto-review**: Ralph Loop stop hook with circuit breakers — bounded iterations prevent overbaking (Gemini recommendation, user agreed)
- **Cross-epic model**: Remove epic serialization, conflict checking at story level — epics are grouping only (Gemini recommendation, user agreed)
- **State storage**: Extend run-state.db with merge_queue, merge_outcomes, agent_heartbeats tables — per decision-76 (transient state in run-state.db)
- **No new memory surfaces**: All new learning flows through existing 3 surfaces — per decision-79

## Constraints
- Must stay within Claude Code primitives (skills, hooks, MCP tools, background agents)
- Must extend existing epics.db and run-state.db — no new state stores (decision-76, decision-79)
- Must respect policy-mechanism split: scripts for mechanisms, SKILL.md for orchestration (decision-78)
- All correction/detection logic stays in signal_processor.py (decision-75, decision-43)
- New context sources must fit the three-tier injection model (decision-66)
- ORCHESTRATION.md section numbers must not be renumbered (downstream reference contract)
- Cannot build separate Go/Rust binaries — stay in Python/Shell
- Must preserve existing correction→preference pipeline

## Reference
- [CooperBench: Why Coding Agents Cannot be Your Teammates Yet](https://arxiv.org/html/2601.13295v1) — peer coordination failure data
- [Grove: Cross-worktree conflict intelligence](https://github.com/NathanDrake2406/grove) — 5-layer conflict detection
- [Clash: git merge-tree for worktrees](https://github.com/clash-sh/clash) — merge simulation approach
- [MemRL: Self-Evolving Agents via Runtime RL on Episodic Memory](https://arxiv.org/html/2601.03192v2) — outcome-based learning
- [Overstory: Multi-agent orchestration](https://github.com/jayminwest/overstory) — FIFO merge queue + watchdog
- [OpenHands SDK V1](https://arxiv.org/html/2511.03690v1) — stuck detection, event-sourced state
- [ralph-claude-code](https://github.com/frankbria/ralph-claude-code) — auto-review loop implementation
- [Cursor BugBot](https://cursor.com/blog/building-bugbot) — agentic review at scale
- [Measuring AI Agent Autonomy — Anthropic](https://www.anthropic.com/research/measuring-agent-autonomy) — organic trust growth data
- [Levels of Autonomy for AI Agents](https://arxiv.org/html/2506.12469v1) — five-level framework
- [Windsurf Cascade Memories](https://docs.windsurf.com/windsurf/cascade/memories) — auto-memory architecture
- [Cursor Rules Empirical Study](https://arxiv.org/html/2512.18925v2) — .mdc rules analysis
