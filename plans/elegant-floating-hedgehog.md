# Plan: `/roadmap` and `/ingest` skills

## Context

There's no current way to go from unstructured research/requirements → structured pipeline work. This plan covers two complementary skills:

1. **`/roadmap`** — takes a research document and produces a structured roadmap markdown file (editable before ingestion)
2. **`/ingest`** — reads a roadmap file and loads it into `epics.json`, routing items to the correct pipeline destination (`agent: manual` → checklist, untagged/`[code]` → epic-planner decomposition)

The intended flow:
```
research doc  →  /roadmap  →  roadmap.md (reviewable)  →  /ingest  →  epics.json
```

---

## Skill 1: `/roadmap`

**File**: `/Users/kelsiandrews/.claude/skills/roadmap/SKILL.md`

### Invocation
```
/roadmap [path-to-research-doc]
```
- If no path: glob `<project-root>/.claude/research/*.md`, list files, ask user to pick.
- If path given: verify exists, read it.

### Behavior

1. **Read the research doc** — full content passed as context.

2. **Launch epic-planner in planning mode** (foreground) with a specialized prompt:
   ```
   MODE: roadmap-conversion
   Research document: <full content>
   Project root: <path>
   Task: Convert this research document into a structured roadmap markdown file.
   Output format: see below.
   Output path: $TMPDIR/roadmap-<slug>.md
   ```
   The planner may ask the user clarifying questions via `AskUserQuestion` (e.g. "Should X be one epic or two?").

3. **Read the output** from `$TMPDIR/roadmap-<slug>.md`.

4. **Write to `<project-root>/.claude/roadmaps/<slug>.md`** — creating the directory if needed.

5. Print:
   ```
   Roadmap written to .claude/roadmaps/<slug>.md
   Review and edit it, then run: /ingest .claude/roadmaps/<slug>.md
   ```

### Roadmap output format (produced by planner)

```markdown
# <Project/Feature Title>

## Epic: <Epic Title>
> <one-sentence description>

### Stories
- [code] <Story title> — <one-line plan>
- [code] <Story title> — <one-line plan>
- [manual] <Manual step description>

## Epic: <Another Epic>
> <description>

### Stories
- [code] <Story title> — <one-line plan>
- [manual] <Manual step description>
```

Tags:
- `[code]` — automated story, goes to orchestrator/epic-planner on ingest
- `[manual]` — human step, becomes a checklist story (`agent: manual`) on ingest
- Untagged items default to `[code]`

### Files to create
| File | Action |
|---|---|
| `/Users/kelsiandrews/.claude/skills/roadmap/SKILL.md` | Create |

---

## Skill 2: `/ingest`

**File**: `/Users/kelsiandrews/.claude/skills/ingest/SKILL.md`

### Invocation
```
/ingest [path-to-roadmap]
```
- If no path: glob `<project-root>/.claude/roadmaps/*.md`, list and prompt.
- If path given: verify exists, read it.

### Behavior

#### 1. Parse the roadmap

Extract structure:
- `## Epic:` lines → epic titles + descriptions
- `- [code]` or untagged `-` lines under `### Stories` → automated stories
- `- [manual]` lines under `### Stories` → manual checklist steps

#### 2. Dedup check

Read `epics.json`. For each epic title, check for existing open epic with same title (case-insensitive). Warn user:
```
Warning: "Authentication" may duplicate epic-007 "Authentication" (running).
Proceed / Skip this epic / Abort
```

#### 3. Classify and group stories

**`[code]` stories** → group by epic, pass to epic-planner for decomposition. Each `[code]` item becomes the description of a story for the planner to size, assign agent/model, and identify write-targets.

**`[manual]` stories** → create directly as pipeline stories with:
```json
{
  "agent": "manual",
  "model": null,
  "state": "filling",
  "branch": null,
  "writeFiles": [".claude/checklists/<epic-slug>.md"],
  "needsTesting": false,
  "needsReview": false
}
```
Also write a corresponding `.claude/checklists/<epic-slug>.md` file with the manual steps pre-populated as `- [ ]` items.

#### 4. Launch epic-planners for `[code]` stories (background, parallel)

One epic-planner per epic that has `[code]` stories:
```
MODE: epic
Epic description: <epic title + description + code story list>
Absolute path to epics.json: <path>
Absolute path to project root: <path>
Output path: $TMPDIR/epic-plan-<epic-slug>.md
Integration surface check: follow §19.2
```

Model: Sonnet default; Opus if epic has >5 code stories or mentions schema/AI changes.

#### 5. Collect, validate, present

When all planners complete:
- Read and validate each `$TMPDIR/epic-plan-<slug>.md` against §6 schema
- Surface validation errors; do not write partial results
- Print consolidated summary (same format as previous `/roadmap` plan — epics, stories, agents, models, integration stories)
- Ask: **approve / abort**

#### 6. Write to epics.json on approval

- Write all new epics and stories (all `state: "filling"`)
- Write checklist files for manual stories
- Create `TaskCreate` entries for each story
- Print: "Ingested N epics, M automated stories, K manual steps. All in filling state."

### Files to create
| File | Action |
|---|---|
| `/Users/kelsiandrews/.claude/skills/ingest/SKILL.md` | Create |

---

## Files to create (summary)

1. `/Users/kelsiandrews/.claude/skills/roadmap/SKILL.md` — research → roadmap conversion skill
2. `/Users/kelsiandrews/.claude/skills/ingest/SKILL.md` — roadmap → epics.json ingestion skill

**Not modified**: ORCHESTRATION.md, existing skills, existing hooks, epics.json (written at runtime only).

---

## Design decisions

- **Epic-planner for `[code]` decomposition**: The skill doesn't size stories or assign agents — that's the planner's job. `/ingest` just passes the story descriptions as the epic's content.
- **`[manual]` items create checklist files automatically**: So the `/checklist` skill can immediately pick them up. The two skills compose naturally.
- **Parallel planners**: One per epic. Large roadmaps (5+ epics) run all planners simultaneously.
- **All stories land in `filling`**: No coders auto-launch. User controls when to run each epic/story.
- **`/roadmap` is a converter, not a planner**: It uses the epic-planner's interactive mode to structure the research doc. The planner asks questions about grouping and scope; the user answers; the roadmap is written.

---

## Verification

1. Create `.claude/research/q3-auth.md` with free-form requirements for an auth feature.
2. Run `/roadmap .claude/research/q3-auth.md` — planner may ask 1-2 grouping questions. Output: `.claude/roadmaps/q3-auth.md` with tagged `[code]`/`[manual]` stories.
3. Edit `q3-auth.md` to add a manual step: `- [manual] Configure OAuth app in provider dashboard`.
4. Run `/ingest .claude/roadmaps/q3-auth.md` — should launch 1 epic-planner for `[code]` items, create 1 manual checklist story directly.
5. Approve — check `epics.json` for new epic + stories in `filling`. Check `.claude/checklists/` for generated checklist file.
6. Run `/status` — new epic appears with mixed automated + manual stories.
7. Run `/checklist q3-auth` — manual step walkthrough starts.
8. Run `/ingest` again on same file — dedup warning fires.
