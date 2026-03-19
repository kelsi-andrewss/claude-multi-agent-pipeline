# Developer Lifecycle AI: Software Factory Patterns

## Problem Statement
**What problem?** AI tools accelerate the 22% of engineering time spent writing code, but the other 78% (requirements decomposition, architecture decisions, environment setup, cross-service integration, review, testing, deployment) still moves at human speed. Cycle time improved only 11% despite 94% AI tool adoption.
**Why fix it?** Without systematic automation of the full lifecycle, the productivity ceiling is hard — individual AI tool usage cannot achieve the factory-level throughput needed for multi-product organizations. Every feature is built from scratch, re-making decisions already made elsewhere.
**Why integral?** This is the core challenge of Gauntlet SF-2026-02: designing a system that transforms feature specs into complete, tested, deployable PRs across multiple products. It's also what our orchestration pipeline already does — this research validates and extends our approach.
**End goal:** A software factory architecture that takes a high-level feature specification and produces a reviewable, CI-passing pull request conforming to the target product's conventions. Not a code generator — a production system covering the full SDLC.

## Overview

The research validates that the industry is converging on a six-component factory architecture: Orchestrator, Planner/Reasoning Engine, Sandbox Executor, Agent-Computer Interface, Memory, and Verification Pipeline. Our orchestration pipeline implements 5 of 6 components, with stronger validation gates and progressive autonomy than any system identified in the research.

The key findings: (1) per-step validation gates matter more than orchestration topology — they nearly double iteration success, (2) self-repair loops have diminishing returns beyond 3-5 iterations for general-purpose LLMs, (3) convention extraction from code is unsolved in production — explicit rules remain the standard, (4) trust requires structured verification contracts and progressive autonomy, not just better code.

## Summary

Research across 184 findings from 40+ authoritative sources (arxiv papers, official docs, case studies) maps current software factory patterns to four areas: codebase intelligence (hybrid three-index fusion emerging as standard), orchestration (DAG/sequential/stateless each dominate different shapes), quality verification (bounded self-repair loops as primary driver), and human-AI trust (progressive autonomy with verification contracts). Our pipeline maps strongly to 5/6 canonical factory components, with the strongest trust calibration system identified in the research and more validation gates than any described system. Gaps: no structural code graph, no containerized sandboxes, no holdout test scenarios.

## Features

### MVP (for Gauntlet challenge: 60 days, 3 engineers, CRUD+UI pattern, 2 products)

0. **Codebase Intelligence Layer** — Per-product convention indexing: CLAUDE.md + decisions.sql per repo, scout-generated pattern files, hierarchical instruction system (.cursorrules-style for each product)
1. **Spec Parser** — Structured JSON input (product, pattern, entity, fields, permissions, integrations, UI) parsed into typed internal representation with validation
2. **Plan Generator** — Gemini decomposes spec into dependency-ordered stages (migrate → api → frontend → tests → config). Each stage gets file-level write targets and acceptance criteria
3. **Code Generator (CRUD+UI pattern)** — Template-aware generation per stage: migration (DB-specific), API endpoints (framework-specific), React/Next.js components (convention-matched), tests (framework-matched), config (env + feature flags + permissions)
4. **Verification Pipeline** — Layered validation: lint → type check → unit test → integration test per stage. Self-repair loop (max 3 iterations). CI simulation before PR creation. Target: 80% first-run pass rate
5. **Review Interface** — Plan-first PR with structured contract: intent summary, impact matrix, per-file rationale, test results, risk tier. Human reviews architecture choices, spot-checks implementation

### Phase 2

6. **Integration pattern** — External service connection (payment processor, EHR, carrier API) with sync logic
7. **Workflow pattern** — Multi-step business processes (approval chains, claim lifecycles)
8. **Analytics pattern** — Dashboard/report generation with aggregation queries
9. **Cross-product convention transfer** — Learn conventions from Product A, apply to Product B

### Cut (v1)

10. Fully autonomous operation (StrongDM "dark factory" — no human review)
11. Containerized sandboxes (Docker/copy-on-write) — worktree isolation sufficient for v1
12. Structural code graph (AST/SCIP indexing) — explicit rules sufficient at 2-product scale

## Technical Research

### Architecture

The factory uses a **hybrid sequential + parallel topology** matching our existing pipeline:

```
Spec Input → Plan Generator (Gemini) → Claude Critique → Dependency-ordered Stage Execution → Per-stage Verification → PR Assembly → Human Review
```

Within stage execution, independent stages run in parallel (matching /run-stories pattern). Dependent stages are serialized.

**Three competing architectures identified:**
1. Multi-agent symphony (Google Jules, Amazon Kira, Factory.ai) — specialized agents per SDLC phase
2. Single-threaded master loop (Claude Code) — simplicity + steerability
3. Static pipeline/Agentless ($0.34/issue vs $10+) — cost efficiency

**Our approach:** Hybrid (1) + (2). Main session orchestrates sequentially; background agents execute in parallel per phase. Matches research finding that topology should match task shape.

### Codebase Intelligence Strategy

**Per-product convention capture (v1):**
- CLAUDE.md per repo (manually authored, highest signal)
- decisions.sql per repo (via decision_memory module)
- Scout-generated pattern files (auto-extracted on first run)
- Hierarchical instruction (.cursorrules-style glob-scoped rules)

**Retrieval at generation time:**
- File-scoped decision injection (just shipped — fnmatch matching)
- Plan files include relevant decisions as constraints
- Convention examples retrieved per-file from the target repo

**v2 (Phase 2):** Three-index fusion for target repos — BM25 (Zoekt) + vector embeddings (Voyage-Code-3 or FastEmbed) + tree-sitter AST graph. RepoCoder-style generate-then-retrieve for convention matching.

Research confirmed: "automatic convention inference from code is unsolved in production." Explicit rules are the correct v1 approach.

### Orchestration Model

**Decomposition:** Gemini parses feature spec JSON → generates dependency-ordered stage list. Each stage is a "story" with:
- Type (db_migration, rest_endpoints, react_components, test_suite, feature_flags_and_permissions)
- depends_on references
- write_files list (from target product's patterns)
- acceptance criteria (testable assertions)

**Execution:** Stages execute in topological order. Independent stages (e.g., migration + config) run in parallel. Dependent stages wait.

**Failure handling:**
- Stage failure triggers bounded self-repair (fix-loop, max 3 iterations)
- If repair fails: BLOCKED, human intervention
- If repair succeeds but downstream stage fails: backtrack to the failed dependency

**Key research finding:** "Per-step validation gates — not the topology — are the critical differentiator, nearly doubling iteration success rates (22.6% → 41.1%)." Our 8-gate validation chain exceeds anything in the research.

### Quality & Verification

**Target: 80% CI pass on first run.**

Research shows this requires:
1. High-quality initial generation (convention-matched, structurally correct)
2. Bounded self-repair (3-5 iterations, not unbounded)
3. Per-stage validation before proceeding to next stage
4. Separate verification agent (dual-model critique)

**Implementation:**
- Each stage runs through: generate → lint → type check → unit test
- Fix-loop with 3-iteration default, circuit breakers for oscillation
- Dual-model critique (Claude self-critique + Gemini escalation)
- Train/test partial isolation: test agent writes from acceptance criteria, not implementation

**Research caution:** "Cumulative correctness across commits degrades even when single-task pass rates are high" (SWE-CI). Batch verification after each merge wave is essential.

### Human Interface & Trust

**Research findings:**
- 84% AI tool usage, 29% trust (widening paradox)
- Reviewers miss 40% more bugs in AI code ("veneer of correctness")
- Complex AI PRs wait 4.6x longer in review queues
- Trust asymmetry: 3 positive experiences to build trust, 1 negative to destroy it

**Implementation:**
- Plan-first review: human approves the PLAN before code generates (Copilot Workspace pattern)
- Structured PR contract: intent, impact matrix, per-file rationale, test results, risk tier
- Progressive autonomy: trust calibration adjusts approval gates per domain
- Human intervention at migration stage (requires_human_approval_before: ["migrate"])

### Patterns (for coder consistency across products)
- **HTTP client**: match target product's existing client (axios, fetch, ky)
- **Error handling**: match target product's error patterns, extracted via scout
- **Validation**: match target product's validation library (zod, joi, manual)
- **Naming**: extracted per-product from scout pattern files
- **Test framework**: match target product's existing framework (jest, pytest, go test)
- **State management**: match target product's patterns (Redux, Zustand, Riverpod)

### Shared Interfaces (factory-level)
- `FeatureSpec` — typed JSON input format (product, pattern, entity, fields, permissions, integrations, UI)
- `GenerationPlan` — stage list with dependency ordering, file targets, acceptance criteria
- `StageResult` — per-stage output (files changed, test results, verification status)
- `PRContract` — structured review artifact (intent, impact, rationale, tests, risk)

### Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Convention drift between scout run and generation | Med | Med | Re-scout on stale conventions (>7 days), diff-gate catches unexpected file changes |
| Cross-product convention transfer produces mismatches | High | Med | v1 keeps products independent; transfer is Phase 2 with explicit human review |
| Self-repair loop oscillation | Med | Low | Circuit breakers: 3 no-progress, 5 same-error recurrence, regression auto-rollback |
| 80% CI pass rate unachievable on first product | High | Med | Fallback: 60% pass rate + bounded repair to 80%. Track and adjust per pattern |
| Human review bottleneck at scale | Med | High | Structured PR contracts reduce review time. Progressive autonomy reduces review gates for proven patterns |

## Test Strategy

### Critical paths
- Spec parser validates all required fields and rejects malformed input
- Plan generator produces dependency-correct stage ordering (migration before API before frontend)
- Generated code passes target product's existing CI pipeline
- Self-repair loop converges within 3 iterations for common failure modes
- PR contract contains all required sections (intent, impact, rationale, tests, risk)

### Edge cases
- Entity with no UI fields (API-only CRUD)
- Sensitive fields (vault_ref) handled correctly — no credential leaks in generated code
- Permissions gating on non-existent roles (graceful creation or error)
- Empty fields array — degenerate but valid spec

### Integration boundaries
- Database migration compatibility with target product's ORM/migration tool
- API endpoint naming conventions match target product's router patterns
- React component conventions match target product's styling system (CSS modules vs Tailwind vs styled-components)
- Test framework configuration compatibility

### What NOT to test
- Route wiring (route configs, middleware registration) — fails obviously
- Type definitions — the type system catches these
- Import organization — linter catches this

## Blast Radius
- **Plan generator changes**: affect all downstream stages. Must validate plan structure before execution.
- **Convention files (CLAUDE.md, decisions.sql)**: affect all generated code for that product. Changes require full re-validation.
- **Self-repair loop changes**: affect all stage recovery. Test with known-failing inputs.
- Confidence: exhaustive for orchestration mapping, best-effort for target product interaction patterns.

## Success Criteria
- Given a CRUD+UI feature spec for an Athena product, the factory produces a deployable PR within 30 minutes
- The PR passes the product's existing CI pipeline on first run >= 80% of the time
- Human review time is under 30 minutes (reviewing architecture, not rewriting code)
- The factory handles at least 2 of the 7 Athena products with the same core system
- Convention compliance: generated code is indistinguishable from team-written code to a reviewer who doesn't know it's AI-generated

## Decisions
- **Orchestration topology**: Hybrid sequential + parallel — matches research finding that topology should match task shape
- **Codebase intelligence v1**: Explicit rules (CLAUDE.md + decisions.sql + scout patterns) — automatic inference is unsolved in production
- **Self-repair bounds**: Max 3 iterations with circuit breakers — matches NeurIPS 2024 findings for general-purpose LLMs
- **Review interface**: Plan-first structured PR contract — research confirms rationale matters more than code for trust
- **Sandbox isolation v1**: Git worktrees — sufficient for story-level isolation, containerization deferred to Phase 2
- **Convention enforcement**: File-scoped decision injection (just shipped) + plan-level constraint injection — proactive, not reactive

## Constraints
- Existing stack: Python/Shell orchestration with Claude Code, Gemini MCP, SQLite, OpenMemory
- 3 engineers, 60 days for v1 (CRUD+UI pattern, 2 products)
- 7 target products, 3 languages (TypeScript, Python, Go), 4 database engines
- SOC 2 and HIPAA compliance for fintech/healthtech products — no credential leaks, auditable output
- Nothing ships without human review (hard constraint, not negotiable)
- Memory infrastructure limited to 3 persistence surfaces (decision-6/decision-79)

## Reference
- [StrongDM Dark Factory](https://simonwillison.net/2026/Feb/7/software-factory/)
- [AgentConductor: Dynamic DAG Topology](https://arxiv.org/html/2602.17100)
- [ReVeal: Iterative Generation-Verification](https://arxiv.org/html/2506.11442v1)
- [Code Review in the Age of AI — Addy Osmani](https://addyo.substack.com/p/code-review-in-the-age-of-ai)
- [Sourcegraph Cody Context Retrieval](https://sourcegraph.com/blog/how-cody-understands-your-codebase)
- [GraphCoder: Code Context Graph](https://arxiv.org/abs/2406.07003)
- [BMAD Method v6.1.0](https://github.com/bmadcode/bmad-method)
- [Stack Overflow 2025: Trust-Adoption Paradox](https://stackoverflow.blog/2026/02/18/closing-the-developer-ai-trust-gap/)
- [NeurIPS 2024: Code Repair Exploration-Exploitation](https://proceedings.neurips.cc/paper_files/paper/2024/)
- Gauntlet SF-2026-02 Case Study (local: ~/Downloads/software-factory-case-study.pdf)
