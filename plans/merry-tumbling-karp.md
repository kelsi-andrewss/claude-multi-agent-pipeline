# Assessment: git-ops skill roadmap path check

## Status: COMPLETE — no git-ops changes needed

## What was checked

The user asked whether the git-ops skill needed updating after the roadmap folder restructure (`.claude/roadmaps/` → `.claude/roadmap/` with index + per-epic subfolders).

## Findings

Searched all files in `skills/` for `.claude/roadmaps` references. Results:

| File | Occurrences | Nature |
|---|---|---|
| `skills/roadmap/SKILL.md` | updated | already fixed |
| `skills/ingest/SKILL.md` | updated | already fixed |
| `skills/roadmap-progress/SKILL.md` | updated | already fixed |
| `skills/checklist/SKILL.md` | 2 | illustrative examples in format reference block — not path-sensitive logic |
| `skills/task/SKILL.md` | 0 | no roadmap references |

There is no git-ops skill file. The git-ops agent only runs bash scripts (`setup-story.sh`, `diff-gate.sh`, `merge-story.sh`, etc.) — none of which touch roadmap files.

The `checklist/SKILL.md` occurrences are example source comments showing what `.claude/roadmaps/auth-system.md` looks like in a comment header. They are illustrative only and do not affect runtime behavior.

## Full skill file list checked

All 27 skill files in `skills/*/SKILL.md` were globbed and the merge skills were read in full.

**merge-story/SKILL.md** — zero roadmap path references. Deals only with epics.json, git branches, and `merge-queue.sh`.

**merge-epic/SKILL.md** — zero roadmap path references. Deals only with epics.json, PRs, and `merge-epic.sh`.

Remaining `.claude/roadmaps/` occurrences after our edits:
- `checklist/SKILL.md:117,226` — illustrative example strings showing what a source comment looks like. Not logic, not path-sensitive.
- `ingest/SKILL.md:315` — the "do not delete/move the roadmap file" note, correctly references both paths.

## Decision

No further edits required.
