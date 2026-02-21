# Claude Multi-Agent Development Pipeline

A structured multi-agent workflow for software development using Claude Code. Epics group related stories, each story gets an isolated worktree branched off the epic feature branch, and specialized agents handle each pipeline stage.

---

## Overview

```
User Request
     │
     ▼
┌─────────────┐
│ Orchestrator│  ← classify, plan, group todos
│  (Haiku)    │
└──────┬──────┘
       │ staging payload
       ▼
┌─────────────┐
│ Main Session│  ← validate, write files, trigger run
└──────┬──────┘
       │ run trigger
       ▼
┌──────────────────────────────────────┐
│           Epic Feature Branch        │
│         epic/<epic-slug>             │
│                                      │
│  ┌──────────┐    ┌──────────┐        │
│  │ Story A  │    │ Story B  │  ...   │
│  │ worktree │    │ worktree │        │
│  └────┬─────┘    └────┬─────┘        │
│       │ merge          │ merge        │
│       └────────┬───────┘             │
│                ▼                     │
│        epic branch HEAD              │
└──────────────────┬───────────────────┘
                   │ epic PR (when ready)
                   ▼
                 main
```

---

## Hierarchy

| Level | Unit | Lives In |
|-------|------|----------|
| **Epic** | Broad theme (e.g. "UI Polish") | `.claude/epics.json` |
| **Story** | Scoped deliverable, owns a branch + worktree | `.claude/epics.json` |
| **Todo** | Atomic task under a story | `.claude/todo-tracking.json` |

---

## Agent Roster

| Agent | Model | Role |
|-------|-------|------|
| `todo-orchestrator` | Haiku (default) | Research, classify, group todos → staging payload. Never writes code. |
| `quick-fixer` | Haiku/Sonnet | Clear-scope fixes, style tweaks, mechanical changes |
| `architect` | Sonnet/Opus | Ambiguous scope, schema changes, new patterns |
| `reviewer` | Haiku | On-demand code review of diffs |
| `unit-tester` | Haiku | Run tests + build; fix trivial failures inline |

### Model Selection

```
orchestrator  → Haiku  (bump to Sonnet/Opus if architecturally complex)
quick-fixer   → Haiku (trivial) | Sonnet (standard) | Opus (escalation)
architect     → Sonnet (standard) | Opus (high-risk, escalation)
reviewer      → Haiku  (Sonnet only if coder was Opus)
unit-tester   → Haiku  always
```

---

## Epic Feature Branch Lifecycle

```
main
 │
 ├─── epic/ui-polish  ──────────────────────────────────────┐
 │         │                                                  │
 │         ├── story/ghost-placement  (worktree)             │
 │         │      └── [coder] → [diff gate] → merge ──►     │
 │         │                                                  │
 │         ├── story/zoom-controls  (worktree)               │
 │         │      └── [coder] → [diff gate] → merge ──►     │
 │         │                                                  │
 │         └── story/text-readability  (worktree)            │
 │                └── [coder] → [diff gate] → merge ──►     │
 │                                                            │
 │         [epic PR created after first story merges]        │
 │         [epic PR updated as each story merges]            │
 │                                                            │
 └── ◄── squash merge when user says "merge epic" ──────────┘
```

### Key Rules

- **Epic branch** — `epic/<slug>`, created off `origin/main` when first story runs
- **Epic branch is persistent** — not deleted after merge to main; stays for follow-up stories
- **Story branches** — `story/<slug>`, created off the epic branch (not main)
- **Stories merge without PRs** — directly into the epic branch via fast-forward or merge commit
- **Epic PR** — created after the first story merges (so the PR has content); updated as more stories land
- **Cross-epic sync** — before creating a story worktree, the epic branch rebases onto `origin/main`

---

## Story Pipeline

```
filling ──► running ──► [testing] ──► merging ──► closed
               │            │
               │       (FAIL: back to running)
               │
               └──► reviewing (on-demand only)
                        │
                   (PASS: merging)
                   (BLOCK: back to running)
```

### State Transitions

| From | To | Trigger |
|------|----|---------|
| `filling` | `running` | User says "run story-X" |
| `running` | `merging` | All coder groups done (default — no tests) |
| `running` | `testing` | All coders done + `needsTesting: true` |
| `testing` | `merging` | Unit-tester PASS |
| `testing` | `running` | Unit-tester FAIL → back to coder |
| `running` | `reviewing` | User requests or `needsReview: true` |
| `reviewing` | `merging` | Reviewer PASS |
| `reviewing` | `running` | Reviewer BLOCKING → back to coder |
| `merging` | `closed` | Merged into epic branch |
| `any` | `blocked` | 2 reviewer retries still blocking (Opus escalation) |

---

## Full Story Run Flow

```
User: "run story-X"
       │
       ▼
1. Read queued todos, check blockedBy ordering
       │
       ▼
2. Create/update epic branch
   ├── No branch yet → create epic/<slug> from origin/main, push
   └── Branch exists → fetch + rebase onto origin/main
       │
       ▼
3. Create story worktree from epic branch
   git worktree add .claude/worktrees/story/<slug> -b story/<slug> epic/<epic-slug>
   ln -sf <root>/.env + node_modules
       │
       ▼
4. Build coderGroups from staging payload
       │
       ▼
5. Launch wave-1 coder groups (background, parallel)
       │
       ▼
6. Wait for all coder groups → done
       │
       ▼
7. MANDATORY DIFF GATE (inline, ~5 seconds)
   git -C <worktree> rebase epic/<epic-slug>
   git -C <worktree> diff epic/<epic-slug>..HEAD --name-only
   → restore any out-of-scope files, commit, verify
       │
       ▼
8. Testing? (needsTesting or write-targets include utils/hooks/testable files)
   ├── YES → launch unit-tester (background)
   │         ├── PASS → proceed
   │         └── FAIL → fix inline or back to coder
   └── NO  → skip
       │
       ▼
9. Review? (user requested or needsReview: true)
   ├── YES → launch reviewer (background)
   │         ├── PASS → proceed
   │         └── BLOCK → increment retries, back to coder (max 2)
   └── NO  → skip
       │
       ▼
10. Merge into epic branch
    git -C <worktree> rebase epic/<epic-slug>
    git checkout epic/<epic-slug>
    git merge --ff-only story/<slug>
    git push origin epic/<epic-slug>
    git worktree remove + prune + branch -d
       │
       ▼
11. Create/update epic PR
    ├── First story → gh pr create --base main --head epic/<slug>
    └── Subsequent → gh pr edit <prNumber> --body (append story)
       │
       ▼
12. Check architectural findings → append novel ones to CLAUDE.md
       │
       ▼
13. Story → closed. Check epic auto-close. /clear
```

---

## Coder Grouping

The orchestrator assigns todos to parallel or sequential groups:

```
For each todo in the story:

1. agent == "architect"
   └── solo group, always (architect never shares a group)

2. agent == "quick-fixer", no overlap with architect
   └── eligible for parallel grouping with other quick-fixers

3. agent == "quick-fixer", overlaps an architect todo
   └── dependsOn that architect group

4. Two quick-fixers share a write-target file
   ├── Different sections → same group
   └── Same section → separate groups, second dependsOn first

5. todo A has blockedBy: todo B (same story)
   └── A's group gets dependsOn = B's group
```

### Example: UI Polish Epic (4 stories, 2 parallel groups)

```
Group A (sequential — share stageHandlers.js):
  Story 1: ghost placement fix  →  Story 2: zoom controls

Group B (sequential — share CSS files):
  Story 3: text readability  →  Story 4: M3 contrast

Groups A and B run in parallel (no file overlap).
```

---

## Protected Files

### Tier 1 — Protected Konva Files (rendering layer)
Agents cannot edit without explicit user permission granted in the current session.

```
src/components/BoardCanvas.jsx
src/components/StickyNote.jsx
src/components/Frame.jsx
src/components/Shape.jsx
src/components/LineShape.jsx
src/components/Cursors.jsx
```

**To unlock:** Say "I grant permission to edit [filename] for this story." The main session notes it in the coder prompt verbatim.

### Tier 2 — Protected Testable Files (have test coverage)
Editing any of these auto-enables `needsTesting: true`. Requires user approval (`testableFilesException: true`).

```
src/hooks/useBoard.js          src/handlers/objectHandlers.js
src/hooks/useBoardsList.js     src/handlers/stageHandlers.js
src/hooks/useRouting.js        src/handlers/transformHandlers.js
src/utils/frameUtils.js        src/components/BoardAccessDenied.jsx
src/utils/connectorUtils.js    src/components/GroupPage.jsx
src/utils/colorUtils.js        src/components/GroupSettings.jsx
src/utils/slugUtils.js         src/components/GroupCard.jsx
src/utils/tooltipUtils.js      src/components/BoardSelector.jsx
                               src/components/BoardSettings.jsx
```

---

## Diff Gate (Mandatory)

Runs inline after all coder groups complete — before tester, reviewer, or merge:

```bash
git -C <worktree> fetch origin
git -C <worktree> rebase epic/<epic-slug>
git -C <worktree> diff epic/<epic-slug>..HEAD --name-only
# Compare against story writeFiles list
# Restore any out-of-scope file:
git -C <worktree> checkout epic/<epic-slug> -- <extra-file>
# If files restored: commit "fix: restore out-of-scope files to epic branch state"
# Re-run diff and verify matches writeFiles exactly
```

---

## On-Demand Testing and Review

### Unit-tester triggers (auto)
| Condition | Result |
|-----------|--------|
| Write-targets include `src/utils/`, `src/hooks/` | `needsTesting: true` |
| Write-targets include any file with `.test.*` counterpart | `needsTesting: true` |
| Story touches permission/admin/Firestore/AI paths | `needsTesting: true` |
| User says "test this story" | `needsTesting: true` |

### Reviewer triggers (on-demand only)
| Condition | Result |
|-----------|--------|
| User says "review this story" | Launch reviewer |
| Story flagged `needsReview: true` | Launch reviewer |
| Story touches frame system, Firestore schema, AI tools | Orchestrator flags `needsReview: true` |

### Diff-only review mode
If the story diff is ≤75 lines, the reviewer reads the diff only — no full files opened. Saves ~80% of reviewer tokens for small stories.

---

## Orchestrator Output Format

```
SUMMARY
Todo: <one-line description>
Story: <storyId> — <story title> [NEW if creating]
Epic: <epicId> — <epic title> [NEW if creating]
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>
Trivial: <yes|no>
Files:
  write: <comma-separated files the coder will modify>
  read: <comma-separated files needed for context only>
Plan: <one sentence describing what the coder will do>
Coder groups: <grouping decision>

STAGING_PAYLOAD
{ "todo": {...}, "storyUpdate": {...}, "epicUpdate": {...} }
```

---

## Context Clearing Rules

Clear (`/clear`) at these mandatory checkpoints:

1. **After fill phase** — after writing a todo and presenting summary
2. **After a story merges** — before auto-launching any queued story
3. **After reviewer + unit-tester both launch** — they wake the session when done
4. **After any background agent completes with no immediate follow-up**

Never clear if a background agent is running and its result is needed to proceed.

---

## Token & Time Optimizations

| Optimization | Savings |
|---|---|
| **Epic-planned stories** — skip orchestrator when epic plan already specifies writeFiles/agent/model | ~2000 tokens/story |
| **CSS-only stories** — always Haiku, skip testing, skip diff gate restoration | ~60% cost reduction |
| **Coder prompt compression** — cap at 2000 tokens; omit full file contents, link CLAUDE.md by section name | ~30-40% token reduction |
| **Diff-only review** — ≤75 line diffs reviewed from diff alone | ~80% reviewer token reduction |
| **Parallel orchestrators** — multiple orchestrators can run simultaneously (read-only) | Wall-time reduction |
| **Batch merge window** — 10-second window to batch same-epic story merges | Fewer rebase cycles |

---

## Escalation

If `reviewerRetries` reaches 2 and the coder is still producing blocking findings:

```
reviewerRetries == 2
       │
       ▼
Escalate coder to Opus (one more attempt)
       │
       ├── PASS → proceed to merge
       └── Still BLOCKING → story.state = "blocked"
                            blockedReason = reviewer findings
                            Leave worktree intact
                            Wait for user intervention
```

---

## Architectural Findings → CLAUDE.md

After each story merge, scan coder output + reviewer warnings + test failure log for novel findings:

- Check if already in CLAUDE.md (Grep for key terms)
- If novel: silently append to appropriate section (Common Gotchas, Architecture Rules, Key Conventions)
- Format: one bullet, concise, actionable
- Triggers: unexpected API behavior, reviewer pattern flag, "framework/API misuse" test failure, new invariant discovered

---

## File Structure

```
~/.claude/
├── CLAUDE.md              # Global preferences (communication, code style, React, Firebase)
├── ORCHESTRATION.md       # This pipeline (main session only)
├── agents/
│   ├── quick-fixer.md
│   ├── architect.md
│   ├── reviewer.md
│   ├── unit-tester.md
│   └── todo-orchestrator.md
└── tracking/
    └── key-prompts/       # High-signal prompt logs (YYYY-MM-DD.md)

<project>/.claude/
├── epics.json             # Epic + story state
├── todo-tracking.json     # Todo state
├── settings.local.json    # File deny rules (protected files)
├── scripts/
│   └── merge-story.sh     # (legacy) story merge script
├── tracking/
│   ├── key-prompts/
│   ├── test-failure-log.md
│   └── review-findings.md
└── worktrees/             # Active story worktrees (cleaned up after merge)
```

---

## Quick Reference

```
New feature request
  └── todo-orchestrator → staging payload → user approval → fill phase

"run story-X"
  └── epic branch created/updated → story worktree created → coders launched

Coder done
  └── diff gate → [unit-tester] → [reviewer] → merge into epic branch → epic PR updated

"merge epic X"
  └── epic branch rebases main → gh pr merge --squash --delete-branch=false → main updated

Epic branch stays alive for follow-up stories.
```
