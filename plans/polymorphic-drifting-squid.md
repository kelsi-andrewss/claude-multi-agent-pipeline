# Plan: Agile pipeline refinement — hierarchy, states, interactivity, fluidity

## Context

The pipeline works but is too rigid for real development. This plan addresses seven problems with a unified set of changes.

**Design decisions** (confirmed with user):
- Epic → Story → Task hierarchy (tasks = lightweight sub-items, not separate branches)
- Move-with-guardrails: free movement with warnings on active coders / broken deps
- Explicit backlog pseudo-epic for uncommitted work
- Agile state names replacing opaque internal ones
- Partial epic merge to unblock shipping

---

## 1. State rename

### Story states

| Old | New | Meaning |
|---|---|---|
| `filling` | `draft` | Being scoped/planned |
| `queued` | `ready` | Dependencies met, ready to start |
| `running` | `in-progress` | Coder actively working |
| `testing` | `in-review` | Testing or code review underway |
| `reviewing` | `in-review` | (merged with testing — same validation phase) |
| `merging` | `approved` | Passed validation, ready to merge to epic |
| `closed` | `done` | Merged into epic branch |
| `blocked` | `blocked` | Stuck, needs intervention |
| *(new)* | `shipped` | Epic merged to main (set on all stories when epic ships) |

### Epic states

| Old | New | Meaning |
|---|---|---|
| *(implicit)* | `active` | Has stories in draft/ready/in-progress/in-review |
| *(implicit)* | `done` | All stories done, PR ready to merge to main |
| *(closed)* | `shipped` | Merged to main |

### Transition map (replaces ORCHESTRATION.md §7 transitions)

```
draft → ready             (run trigger, dependencies met)
draft → ready             (run trigger, no dependencies)
ready → in-progress       (coder launched)
in-progress → in-review   (coder done, testing or review needed)
in-progress → approved    (coder done, no testing/review needed)
in-review → in-progress   (test/review failed, send back to coder)
in-review → approved      (test/review passed)
approved → done           (merged into epic branch)
done → shipped            (epic merged to main)
any → blocked             (stuck)
blocked → in-progress     (manual reset)
any → draft               (rescoped — pulled back to planning)
```

### Files that need state rename

**Global (~/.claude/)**:
- `ORCHESTRATION.md` — 18 occurrences
- `refs/staging-schema.md` — transition map + valid states
- `refs/output-formats.md` — state references in examples
- `refs/protected-files-template.md` — minor
- `hooks/guard-direct-edit.sh` — checks `running`, `testing`, `reviewing`, `merging`
- `hooks/load-session-context.sh`, `warn-sync-heavy-bash.sh`, `cost-alert.sh` — grep to confirm
- 13 skill files (all listed in exploration)

**Project-level (deferred — not in this plan)**:
- `gauntlet/week1/.claude/scripts/merge-story.sh`
- `gauntlet/openemr/.claude/scripts/merge-story.sh`, `update-epics.sh`
- Any `epics.json` files with existing stories (need migration)

**Migration strategy**: Add a `migrateStates()` helper to `update-epics.sh` that maps old→new on read. Existing epics.json files work until next write, at which point states auto-migrate.

---

## 2. Task sub-items

### Schema addition to story objects

```json
{
  "id": "story-042",
  "tasks": [
    {"id": "t1", "title": "Implement Google OAuth endpoint", "state": "done"},
    {"id": "t2", "title": "Implement GitHub OAuth endpoint", "state": "in-progress"},
    {"id": "t3", "title": "Add OAuth callback handler", "state": "todo"},
    {"id": "t4", "title": "Write integration tests", "state": "blocked", "blockedBy": "t3"}
  ]
}
```

Task states: `todo`, `in-progress`, `done`, `blocked`, `skipped`.

**Backward compat**: `tasks` is optional. Stories without it display normally.

### `/task` skill (new)

```
/task add story-042 "Write integration tests"
/task done story-042 t3
/task block story-042 t4 --by t3
/task skip story-042 t2
/task list story-042
/task remove story-042 t4
```

All operations via update-epics.sh with patch format:
```json
{"storyId":"story-042","addTask":{"title":"Write tests"}}
{"storyId":"story-042","taskId":"t3","fields":{"state":"done"}}
```

### How tasks get populated

- **Orchestrator/planner**: Include tasks in staging payload
- **Ingest**: Code story sub-bullets → tasks
- **Manual**: `/task add`
- **Coder output**: Reports "done: t1 — ..." → main session updates

---

## 3. Backlog

### Schema

```json
{
  "id": "epic-backlog",
  "title": "Backlog",
  "branch": null,
  "prNumber": null,
  "persistent": true,
  "isBacklog": true,
  "state": "active"
}
```

Auto-created on first use if not present.

### `/backlog` skill (new)

```
/backlog "Investigate caching"          — create draft story in backlog
/backlog                                — list backlog stories
/backlog promote story-099 epic-005     — move to epic
```

### `/defer story-X` skill (new)

Move story to backlog. Guardrails:
- Running coder → warn, require confirmation
- Dependency chain → warn, offer to clear dependsOn on downstream stories
- Active branch/worktree → warn about orphaned branch

### `/todo "desc" --backlog`

Stages directly to backlog, no orchestrator.

---

## 4. Story movement

### `/move story-X epic-Y` skill (new)

Guardrails before moving:
1. **In-progress coder**: warn, require abort or wait
2. **Broken dependencies**: list affected stories, offer to clear
3. **Active branch**: note it will be orphaned, clear `branch` field
4. **Active worktree**: warn about uncommitted changes

### `/split story-X` skill (new)

Interactive:
1. Show tasks (or writeFiles if no tasks)
2. User picks which go to new story
3. New story created in same epic with selected items
4. Original keeps the rest

### `/rescope story-X` skill (new)

Interactive modification:
1. Show current tasks and writeFiles
2. Options: add/remove task, change writeFiles, change agent/model
3. If in-progress: warn changes won't affect running coder

---

## 5. Flexible checklists

### New actions via flags

| Command | Action |
|---|---|
| `/checklist <name>` | Walk interactively (unchanged) |
| `/checklist <name> status` | Numbered steps + progress bar |
| `/checklist <name> mark <N>` | Mark step N done (or text substring match) |
| `/checklist <name> unmark <N>` | Undo completed step |
| `/checklist <name> add "<text>"` | Append step |
| `/checklist <name> add "<text>" --after <N>` | Insert after step N |
| `/checklist <name> remove <N>` | Remove step (confirm first) |
| `/checklist <name> reorder <from> <to>` | Move step position |
| `/checklist <name> source` | Show roadmap provenance |

### Source link (written by ingest)

```markdown
<!-- source: .claude/roadmaps/auth-system.md | epic: epic-005 | story: story-042 -->
```

### `/checklist <name> status` output

```
Checklist: deploy (story-088, epic-012)
Source: .claude/roadmaps/deploy-pipeline.md

  1. [x] Create API key in provider dashboard
  2. [x] Add key to .env.production
  3. [ ] Rotate and revoke the old key
  4. [ ] Smoke-test the endpoint

Progress: [████████░░░░░░░░░░░░] 2/4 (50%)

Actions: /checklist deploy mark 3 | /checklist deploy add "..."
```

---

## 6. Interactive roadmap-progress

### Flag modes

- `/roadmap-progress` — summary + interactive menu
- `/roadmap-progress epic-005` — drill into one epic
- `/roadmap-progress --stalled` — only epics with draft/blocked stories
- `/roadmap-progress --shipped` — include shipped epics

### Interactive menu (after summary table)

```
[1] Drill into an epic
[2] Show stalled stories
[3] Show backlog
[4] Done
```

Drill-in shows:
- Stories with state (colored), agent/model
- Task progress: "3/5 tasks done"
- Manual stories: checklist completion "2/4 steps done"
- Action hints: "run", "defer", "rescope"

### Cross-linking

Read checklist files for manual stories, count `[x]` vs `[ ]`. Read story `tasks` arrays for code stories.

### State bucket mapping (updated for new states)

- `draft` bucket: `draft`, `ready`
- `active` bucket: `in-progress`, `in-review`, `approved`, `blocked`
- `done` bucket: `done`, `shipped`

---

## 7. Partial epic merge

### `/merge-epic epic-X --partial`

1. Verify ≥1 story is `done`.
2. List open stories, ask to proceed.
3. On yes: squash-merge epic PR. Create continuation epic `<title> (cont)` with open stories re-parented. Note branches needing rebase.
4. Set shipped stories to `shipped`. Set original epic to `shipped`.

### ORCHESTRATION.md §13 addition

```
**Partial merge**: `/merge-epic --partial` merges done stories to main and
moves open stories to a continuation epic. See /merge-epic skill.
```

---

## 8. Status enhancements

### Task progress for code stories
```
story-042  [in-progress]  Add OAuth login  architect  sonnet  (1/4 tasks)
```

### Checklist progress for manual stories
```
story-088  [in-progress]  Checklist: deploy  manual  (2/4 steps)
```

### Backlog section
```
Backlog (3 stories):
  story-099  [draft]  Investigate caching strategy
  ...
```

### Quick actions footer
```
Actions: /run-story <id> | /defer <id> | /checklist <name> | /promote <id> <epic>
```

---

## 9. Ingest improvements

### Source comment in checklist files

Prepend when writing (Step 5):
```markdown
<!-- source: .claude/roadmaps/<slug>.md | epic: <epic-id> | story: <story-id> -->
```

### Sub-bullets → tasks (for code stories)

When parsing new-format roadmaps, code story sub-bullets become `tasks` array entries:
```markdown
- Add login endpoint
  - Implement POST /auth/login with bcrypt check
  - Return signed JWT with 24h expiry
```
→
```json
{"title": "Add login endpoint", "tasks": [
  {"id": "t1", "title": "Implement POST /auth/login with bcrypt check", "state": "todo"},
  {"id": "t2", "title": "Return signed JWT with 24h expiry", "state": "todo"}
]}
```

### `/ingest --update <path>`

1. Parse roadmap, find matching epics in epics.json.
2. Diff: new stories → offer to add. Missing stories → offer to archive (move to backlog). Changed sub-bullets → offer to update tasks.
3. Write via update-epics.sh on approval.

---

## File change summary

| File | Action | Changes |
|---|---|---|
| `ORCHESTRATION.md` | Modify | State rename (18 occurrences), §7 new transitions, §13 partial merge, tasks/backlog schema |
| `refs/staging-schema.md` | Modify | New states, tasks array, backlog epic |
| `refs/output-formats.md` | Modify | State references in examples |
| `hooks/guard-direct-edit.sh` | Modify | `running`→`in-progress`, `testing`/`reviewing`→`in-review`, `merging`→`approved` |
| `hooks/load-session-context.sh` | Modify | State references |
| `hooks/warn-sync-heavy-bash.sh` | Modify | State references |
| `hooks/cost-alert.sh` | Modify | State references (if any) |
| `skills/roadmap-progress/SKILL.md` | Rewrite | Flags, interactive menu, drill-down, cross-links, new states |
| `skills/checklist/SKILL.md` | Rewrite | Flag actions, source link, new states |
| `skills/merge-epic/SKILL.md` | Modify | `--partial` flag, new states |
| `skills/status/SKILL.md` | Modify | Task/checklist progress, backlog section, new states |
| `skills/ingest/SKILL.md` | Modify | Source comments, sub-bullets→tasks, `--update`, new states |
| `skills/todo/SKILL.md` | Modify | `--backlog` flag, new states |
| `skills/merge/SKILL.md` | Modify | New states |
| `skills/run-story/SKILL.md` | Modify | New states |
| `skills/recover/SKILL.md` | Modify | New states |
| `skills/clear-guide/SKILL.md` | Modify | New states |
| `skills/lint/SKILL.md` | Modify | New states |
| `skills/hotfix/SKILL.md` | Modify | New states |
| `skills/quickfix/SKILL.md` | Modify | New states |
| **New** `skills/task/SKILL.md` | Create | Task CRUD |
| **New** `skills/backlog/SKILL.md` | Create | Backlog management |
| **New** `skills/defer/SKILL.md` | Create | Move to backlog with guardrails |
| **New** `skills/move/SKILL.md` | Create | Move between epics with guardrails |
| **New** `skills/split/SKILL.md` | Create | Split story into two |
| **New** `skills/rescope/SKILL.md` | Create | Re-scope story tasks/files |

**Total**: 20 files modified, 6 files created

---

## Implementation order

**Phase 1 — Schema + state rename** (foundation, everything else depends on this):
1. `ORCHESTRATION.md` — state rename + tasks/backlog schema
2. `refs/staging-schema.md` — updated schema
3. `refs/output-formats.md` — state references
4. All 4 hooks — state references
5. All 13 existing skills — mechanical state rename

**Phase 2 — New primitives** (task, backlog, movement):
6. `skills/task/SKILL.md` — task CRUD
7. `skills/backlog/SKILL.md` — backlog management
8. `skills/defer/SKILL.md` — move to backlog
9. `skills/move/SKILL.md` — move between epics

**Phase 3 — Interactivity** (depends on new states + tasks):
10. `skills/checklist/SKILL.md` — flag actions rewrite
11. `skills/ingest/SKILL.md` — source comments + tasks + --update
12. `skills/status/SKILL.md` — task/checklist progress + backlog
13. `skills/roadmap-progress/SKILL.md` — interactive rewrite

**Phase 4 — Advanced** (independent):
14. `skills/merge-epic/SKILL.md` — --partial flag
15. `skills/split/SKILL.md` — story splitting
16. `skills/rescope/SKILL.md` — story rescoping

Phases 2-4 can partially overlap. Phase 1 must complete first.

---

## Verification

1. State rename: `/status` shows new state names with correct colors
2. `/task add story-042 "Write tests"` → task t5 appears in story
3. `/task done story-042 t1` → marks done
4. `/backlog "Explore caching"` → draft story in backlog epic
5. `/defer story-044` → warns about running coder, moves to backlog
6. `/move story-099 epic-005` → promotes with guardrails
7. `/checklist deploy mark 3` → marks step 3 without walking
8. `/checklist deploy status` → numbered list + progress bar + source link
9. `/roadmap-progress` → interactive menu
10. `/roadmap-progress epic-005` → drill-down with tasks
11. `/merge-epic epic-005 --partial` → ships done, moves open to continuation
12. `/ingest --update roadmap.md` → diffs and offers additions
13. `/split story-042` → interactive split
14. `/rescope story-042` → change tasks/files
15. Hooks still work: guard-direct-edit blocks non-worktree edits for `in-progress` stories
