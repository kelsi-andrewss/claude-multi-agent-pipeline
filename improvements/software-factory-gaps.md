# Software Factory Gaps

Identified via /research on developer lifecycle AI best practices, mapped against our orchestration pipeline via /scout. Source: presearch/developer-lifecycle-ai-software-factory.md

## Build Now (High Impact)

### 1. Holdout Test Scenarios
**Gap:** Test agent sees the plan file which describes the implementation approach. No true train/test isolation.
**Target:** Acceptance criteria generated BEFORE implementation, invisible to the coder. Holdout BDD/Gherkin scenarios that validate behavior without knowledge of implementation.
**Research:** StrongDM Dark Factory pattern — holdout scenarios deliberately kept invisible to coding agent to prevent test gaming. Train/test isolation is "the critical architectural invariant."
**Status:** SHIPPED (story-863, epic-193). HTML comment delimiters `<!-- CODER_ONLY -->` / `<!-- TESTER_ONLY -->` in plan files. Backward-compatible.

### 2. Spec-Driven Development
**Gap:** Specs and acceptance criteria are generated alongside implementation plans, not independently before implementation begins.
**Target:** Structured JSON spec input → dependency-ordered generation plan. Specs define WHAT, plans define HOW. Specs are immutable once approved; plans can iterate.
**Research:** SDD pattern — agents generate specs + acceptance tests BEFORE implementation. PR gate only opens if agent provides logs proving those tests passed in sandbox.
**Status:** SHIPPED (story-864, epic-193). New /factory skill accepts FeatureSpec JSON, decomposes via pattern DAGs (CRUD+UI, Integration, Workflow, Analytics), outputs .ship-manifest.json.

### 3. Per-Product Convention Extraction
**Gap:** All conventions are manually authored in CLAUDE.md. No automated extraction for new target repos.
**Target:** Auto-generate convention files (CLAUDE.md + decisions.sql + pattern files) for any target repo on first run via enhanced /scout.
**Research:** Convention enforcement via hierarchical instruction (Cursor MDC+glob, copilot-instructions.md). Automatic inference unsolved, but structured extraction on demand is tractable.
**Status:** SHIPPED (story-865, epic-193). New `--bootstrap` mode generates CLAUDE.md, decisions.sql, .claude/refs/ for target repos. 3 generator scripts + bootstrap-prompt.md.

## Build Next (Medium Impact)

### 4. Cumulative Correctness Tracking
**Gap:** Batch verification catches build breaks but not semantic regressions across stories.
**Target:** Track behavioral correctness across story merges — detect when Story B's changes break Story A's acceptance criteria even if CI passes.
**Research:** SWE-CI found "zero-regression rates below 0.25 on long-horizon CI maintenance tasks" — isolated task pass rates don't predict cumulative correctness.
**Status:** SHIPPED (story-866, epic-193). New regression-check.py script + regression_events table. Scoped to current epic, filtered by write_files overlap. Step 5.6 in merge-worktree.

### 5. Cost-Per-Iteration Tracking
**Gap:** Fix-loop tracks iteration count and error hashes but not token cost per iteration.
**Target:** Track token spend per fix-loop retry. Identify the cost-quality tradeoff curve. Feed into 80% pass rate optimization.
**Research:** NeurIPS 2024 — "diminishing or negative returns beyond moderate retry budgets." No published cost-benefit analysis for self-healing iterations.
**Status:** SHIPPED (story-867, epic-193). Per-iteration token tracking + USD cost calculation. fix_iterations table in run-state.db. Model pricing for Sonnet/Opus.

## Defer (Low Impact or Unsolved)

### 6. Containerized Sandboxes
**Gap:** Worktrees provide git isolation only, not process/filesystem isolation.
**Why defer:** Worktree isolation sufficient for story-level parallel execution. Containerization adds complexity for marginal benefit at current scale.
**Revisit when:** Agents start touching production infrastructure, databases, or network services directly.

### 7. Convention Inference from Code
**Gap:** No automatic inference of conventions from code patterns.
**Why defer:** Research confirms this is unsolved in production. All tools (Cursor, Cody, Copilot) use explicit developer-authored rules. RepoCoder treats convention as retrieval problem — interesting but not deployed.
**Revisit when:** RepoCoder-style generate-then-retrieve becomes production-ready.

### 8. Structural Code Graph (AST/SCIP)
**Gap:** No AST or semantic graph over the codebase for retrieval.
**Why defer:** Explicit rules + decision injection adequate at 2-product scale. Three-index fusion warranted for target projects at scale, not for the orchestration infra itself.
**Revisit when:** Scaling beyond 5 target products or when cross-file retrieval accuracy becomes a bottleneck.

### 9. Custom Agent-Computer Interface
**Gap:** Inherited from Claude Code — no custom interception layer for high-risk commands.
**Why defer:** Claude Code's native tool interface (Read/Write/Edit/Bash) is sufficient. Hooks provide enforcement layer.
**Revisit when:** Agents need to interact with production systems directly.

### 10. Trust Calibration Cold Start
**Gap:** Trust-informed model selection requires 10+ merge_outcomes before activating.
**Why defer:** 10-sample minimum is statistically reasonable. Static table fallback works for new projects.
**Revisit when:** Onboarding new projects frequently enough that cold start becomes a friction pattern.
