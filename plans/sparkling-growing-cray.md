# Plan: Fast-lane skills + refs system + ORCHESTRATION.md compression

## Context

Three related problems:
1. **Pipeline too slow for small fixes** — even a 1-line CSS change requires orchestrator → epics.json → worktree → coder → diff gate → merge. Need `/hotfix` and `/quickfix` fast lanes.
2. **ORCHESTRATION.md is 918 lines** — bloated with duplicated procedures (already encoded in skills), project-specific pitfalls, verbose JSON schemas, and scattered protected-file rules.
3. **Project-specific config baked into global files** — Konva pitfalls, protected file lists, Firebase gotchas all live in global ORCHESTRATION.md but only apply to CollabBoard.

**Solution**: A three-part change:
- **Global refs** (`~/.claude/refs/`) — reusable boilerplate pitfalls, schemas, formats
- **`/refine` skill** — reads refs, scans project, generates project-specific orchestration config with hybrid hash-stamped inlining
- **`/hotfix` + `/quickfix` skills** — fast lanes with enforced guardrails
- **ORCHESTRATION.md compression** — deduplicate against skills, extract to refs, remove project-specific content

---

## Part 1: Global refs system

### New directory: `~/.claude/refs/`

| File | Content | Extracted from |
|---|---|---|
| `pitfalls-konva.md` | Konva Groups .width()/.height(), transformer cleanup, getClientRect, memo equality | ORCHESTRATION.md §10 |
| `pitfalls-react.md` | Async state in callbacks, ref patterns, useEffect cleanup, memo gotchas | ORCHESTRATION.md §10 |
| `pitfalls-firebase.md` | writeBatch limits (500), batch.update vs set, consistency windows, deleteSet guard | ORCHESTRATION.md §10 + CLAUDE.md |
| `pitfalls-css.md` | focus-visible contrast, flex parent check, no !important, CSS variables | ORCHESTRATION.md §10 + CLAUDE.md |
| `staging-schema.md` | Staging payload JSON schema + field reference + validation rules | ORCHESTRATION.md §5 + §6 |
| `output-formats.md` | Orchestrator output, NEEDS_PLANNING output, epic-planner output, coder result blocks | ORCHESTRATION.md §5, §19, §19.1 |
| `protected-files-template.md` | Template for project protected files — instructs `/refine` what to ask | New |

Each pitfalls file is ~15-25 lines. Schema/format files are ~30-40 lines each.

---

## Part 2: `/refine` skill

### `~/.claude/skills/refine/SKILL.md`

```yaml
---
name: refine
description: >
  Generate project-specific orchestration config from global refs. Scans the
  project, asks targeted questions, and produces project-orchestration.md with
  relevant pitfalls inlined and hash-stamped. Use /refine for initial setup,
  /refine --refresh to pull updated refs, /refine --check for staleness check.
args:
  - name: flags
    type: string
    description: "Optional: --refresh (re-pull refs), --check (staleness only)"
---
```

**Steps (initial run)**:

1. **Scan project**: Glob for framework signals:
   - `react` / `react-dom` in package.json → include pitfalls-react.md
   - `konva` / `react-konva` → include pitfalls-konva.md
   - `firebase` / `@firebase/*` → include pitfalls-firebase.md
   - Any `.css` / `.scss` / `.module.css` files → include pitfalls-css.md
2. **Ask questions** via AskUserQuestion:
   - "Which files should be protected from casual edits?" (suggest detected component files)
   - "Any files that always require testing when changed?" (suggest src/utils/, src/hooks/)
   - "Custom pitfalls specific to this project?" (free text)
3. **Generate `<project>/.claude/project-orchestration.md`**:
   - Header with generation timestamp and ref hashes
   - `## Protected files` — user's answers from step 2
   - `## Pitfalls` — relevant refs inlined, grouped by category
   - `## Scope triggers` — which file patterns trigger testing, review, etc.
   - `## Custom` — project-specific pitfalls from user input
4. **Generate `<project>/.claude/protected-files.md`** — standalone list for hooks to read
5. **Stamp hashes** in project-orchestration.md header:
   ```
   <!-- ref-hashes: pitfalls-konva=a1b2c3 pitfalls-react=d4e5f6 pitfalls-css=g7h8i9 -->
   ```

**Steps (`--refresh`)**:

1. Read existing project-orchestration.md
2. For each ref hash in header: compute current hash, compare
3. For stale refs: re-read global ref, replace inlined section, update hash
4. Preserve custom sections untouched

**Steps (`--check`)**:

1. Read hashes from project-orchestration.md header
2. Compare against current global refs
3. Report: "2 refs are stale: pitfalls-konva.md, pitfalls-css.md. Run /refine --refresh"
4. No file modifications

**Staleness check integration**: The pre-response-check skill or session-start hook can run `/refine --check` silently once per session. If stale, surface a one-line warning — don't block.

---

## Part 3: ORCHESTRATION.md compression

### What gets removed/compressed

| Change | Lines saved |
|---|---|
| §1 corollaries: delete 4 redundant corollaries, keep ZERO-SKIP + epics.json-only | ~8 |
| §4 procedure → "See /todo skill" + policy rules only | ~50 |
| §5 staging schema → "See refs/staging-schema.md" | ~30 |
| §5 output formats → "See refs/output-formats.md" | ~40 |
| §9 run trigger procedure → "See /run-story skill" | ~25 |
| §10 pitfalls list → routing table to refs/ | ~20 |
| §10 protected files → "See <project>/protected-files.md" | ~15 |
| §12 merge procedure → "See /merge skill" | ~30 |
| §13 epic merge procedure → "See /merge-epic skill" | ~15 |
| §15 recovery procedure → "See /recover skill" | ~15 |
| §19 planner output format → "See refs/output-formats.md" | ~15 |
| §19.1 planning output format → same | ~12 |
| **Total** | **~275 lines** |

### What stays in ORCHESTRATION.md

- §1 ENFORCEMENT — ZERO-SKIP rule + exceptions for /hotfix, /quickfix
- §2 AGENT ROLES — role definitions with consolidated "read-only" constraint
- §3 MODEL SELECTION — lookup table (already compact)
- §4 ROUTING — policy rules only (4 routing categories + skill link)
- §7 EPIC/STORY STRUCTURE — data model + state machine (already clean)
- §8 FILL PHASE — /clear rules
- §10 CODER GROUPING — decision tree + pitfalls routing table (refs links)
- §11 PIPELINE EXECUTION — flow rules, escalation, post-merge checks
- §14 PARALLEL STORY EXECUTION — ordering + conflict protocol
- §16 BACKGROUND AGENT MANAGEMENT — stall detection
- §17 LOGGING — log formats
- §18 TOKEN OPTIMIZATIONS — prompt sizing rules
- §19 EPIC PLANNER — trigger + constraints (output format extracted)
- §19.2 INTEGRATION SURFACES — detection algorithm
- **New §20 HOTFIX PATH** — qualification + policy (procedure in skill)
- **New §21 QUICKFIX PATH** — qualification + policy (procedure in skill)

**Estimated result**: ~550-600 lines (down from 918)

### Pitfalls routing table (replaces inline list in §10)

```
Include pitfalls relevant to write-targets from project-orchestration.md.
If no project-orchestration.md exists, read global refs directly:
- Components using Konva: ~/.claude/refs/pitfalls-konva.md
- Hooks/async handlers: ~/.claude/refs/pitfalls-react.md
- Firestore mutations: ~/.claude/refs/pitfalls-firebase.md
- CSS/styling changes: ~/.claude/refs/pitfalls-css.md
```

---

## Part 4: `/hotfix` skill

### `~/.claude/skills/hotfix/SKILL.md`

```yaml
---
name: hotfix
description: >
  Fastest pipeline path for single-file, non-protected, known-root-cause fixes
  of ≤30 lines. Edits inline on a temp branch, merges via auto-squashed PR.
  Use when the user says "/hotfix", "hotfix: ...", or for trivial one-file fixes.
args:
  - name: description
    type: string
    description: "What to fix and in which file (e.g. 'fix button color in src/components/Toolbar.jsx')"
---
```

**Steps**:

1. **Parse**: Extract target file path and fix description from `{{description}}`
2. **Qualification gate** (ALL must pass or reject → suggest `/quickfix` or `/todo`):
   - Exactly 1 file, file exists
   - Not in project's protected files list (`<project>/.claude/protected-files.md`, fallback to hardcoded Konva list)
   - Not in `src/utils/`, `src/hooks/`, no `.test.*` counterpart
   - No schema/frame/AI tool changes
   - Dedup: no running/filling story in epics.json covers this file
3. **Print summary**, ask user to confirm (skip with `--yes`)
4. **Branch**: `git checkout -b hotfix/<slug> main`
5. **Write sentinel**: `/tmp/hotfix-active-<PPID>` containing target file absolute path
6. **Edit**: Main session edits the file inline via Edit tool
7. **Post-edit check**: `git diff --stat` — if >30 lines changed, abort with "Use /quickfix"
8. **Build**: `npm run build` (foreground, must pass)
9. **Commit**: `git add <file>` + commit
10. **PR**: Push branch, `gh pr create --base main`, `gh pr merge --squash --delete-branch`
11. **Cleanup**: `git checkout main`, `git pull`, remove sentinel, append to `<project>/.claude/hotfix-log.md`

### Guard hook modification: `~/.claude/hooks/guard-direct-edit.sh`

Add after the temp-file allow (line 49), before the epics.json check (line 52):

```bash
# Allow edits during active /hotfix — sentinel contains allowed file path
HOTFIX_SENTINEL="/tmp/hotfix-active-${PPID:-$$}"
if [[ -f "$HOTFIX_SENTINEL" ]]; then
  ALLOWED_FILE=$(cat "$HOTFIX_SENTINEL")
  if [[ "$FILE_PATH" == *"$ALLOWED_FILE"* || "$ALLOWED_FILE" == *"$FILE_PATH"* ]]; then
    exit 0
  fi
fi
```

---

## Part 5: `/quickfix` skill

### `~/.claude/skills/quickfix/SKILL.md`

```yaml
---
name: quickfix
description: >
  Lighter-than-/todo path for 1-3 file fixes with known root cause. Uses a
  worktree and background coder but skips orchestrator and epics.json tracking.
  Merges via auto-squashed PR. Supports --test flag for testable files.
args:
  - name: description
    type: string
    description: "What to fix and which files (e.g. 'fix drag offset in src/handlers/dragHandler.js, src/components/DragPreview.jsx')"
---
```

**Steps**:

1. **Parse**: Extract file paths (1–3) and description
2. **Qualification gate** (ALL must pass or reject → suggest `/todo`):
   - 1–3 files, all exist
   - None in project's protected files list
   - Testable file check: if any in `src/utils/`, `src/hooks/`, or has `.test.*` counterpart → ask user, set `needsTesting = true`
   - No schema/frame/AI tool changes
   - Dedup against epics.json
3. **Print summary**, ask user to confirm
4. **Branch + worktree** (inline git, no setup-story.sh):
   ```
   git checkout -b quickfix/<slug> origin/main
   git worktree add .claude/worktrees/quickfix/<slug> quickfix/<slug>
   ```
   Symlink `.env` and `node_modules`
5. **Launch quick-fixer** (background, Haiku) with write-targets, relevant pitfalls from project-orchestration.md, CWD note
6. **On coder complete**: Inline diff gate — verify only declared files changed, restore any out-of-scope files
7. **Build**: `npm run build` in worktree
8. **If `needsTesting`**: Launch unit-tester (background), wait
9. **PR**: Push branch, `gh pr create --base main`, `gh pr merge --squash --delete-branch`
10. **Cleanup**: Remove worktree, delete local branch, append to `<project>/.claude/hotfix-log.md`

---

## Part 6: Pre-response-check update

### Modify `~/.claude/skills/pre-response-check/SKILL.md`

Add to constraints:

> **Lightweight path routing**: If a code-changing request qualifies for `/hotfix` (single file, ≤30 lines, known cause) or `/quickfix` (1-3 files, known cause), suggest the lighter path. Don't default to `/todo` for everything.

> **Staleness check**: If project-orchestration.md exists, check ref hashes once per session. Surface warning if stale.

---

## Guardrails against misuse

**Hard blockers** (skill rejects, cannot override):
- Protected file → rejected
- File count exceeded → rejected
- >30 lines post-edit (hotfix) → aborted, suggest `/quickfix`
- Schema/frame/AI target → rejected
- Existing story covers file → rejected

**Soft guardrails** (warnings):
- Frequency cap: warn after 3 hotfixes or 2 quickfixes per session
- Audit log: every hotfix/quickfix appended to `<project>/.claude/hotfix-log.md`

---

## Implementation order

1. **Create `~/.claude/refs/`** — 7 ref files extracted from ORCHESTRATION.md
2. **Create `/refine` skill** — self-contained, no dependencies on other new work
3. **Compress ORCHESTRATION.md** — deduplicate procedures, link to skills, link to refs, add §20/§21 stubs
4. **Modify `guard-direct-edit.sh`** — add sentinel check for /hotfix
5. **Create `/hotfix` skill**
6. **Create `/quickfix` skill**
7. **Update `pre-response-check` skill** — lightweight path routing + staleness check

Steps 1-2 can run in parallel with step 3. Steps 4-6 depend on step 3 (ORCHESTRATION.md must have §20/§21). Step 7 is last.

---

## Files summary

| Action | File |
|---|---|
| Create | `~/.claude/refs/pitfalls-konva.md` |
| Create | `~/.claude/refs/pitfalls-react.md` |
| Create | `~/.claude/refs/pitfalls-firebase.md` |
| Create | `~/.claude/refs/pitfalls-css.md` |
| Create | `~/.claude/refs/staging-schema.md` |
| Create | `~/.claude/refs/output-formats.md` |
| Create | `~/.claude/refs/protected-files-template.md` |
| Create | `~/.claude/skills/refine/SKILL.md` |
| Create | `~/.claude/skills/hotfix/SKILL.md` |
| Create | `~/.claude/skills/quickfix/SKILL.md` |
| Modify | `~/.claude/ORCHESTRATION.md` (compress ~918 → ~600 lines) |
| Modify | `~/.claude/hooks/guard-direct-edit.sh` (add sentinel check) |
| Modify | `~/.claude/skills/pre-response-check/SKILL.md` (add routing + staleness) |

---

## Verification

1. **Refs**: Each ref file is self-contained and readable standalone
2. **`/refine`**: Run on CollabBoard project → should detect React+Konva+Firebase, ask about protected files, generate project-orchestration.md with hashes
3. **`/refine --check`**: Modify a global ref → should report staleness
4. **`/refine --refresh`**: Should update stale sections, preserve custom sections
5. **ORCHESTRATION.md**: Read through compressed version — all policy rules present, no dangling refs to removed content
6. **`/hotfix`**: Create branch, edit single file, build, PR, merge, cleanup — all in one invocation
7. **`/hotfix` rejection**: Protected file → rejected. >30 lines → aborted.
8. **Guard hook**: Without sentinel, main-session edits still blocked
9. **`/quickfix`**: Worktree, coder, diff gate, build, PR, cleanup — lighter than /todo
10. **`/quickfix --test`**: Testable file triggers unit-tester after coder
11. **Pre-response-check**: Suggest /hotfix for trivial single-file request instead of /todo
