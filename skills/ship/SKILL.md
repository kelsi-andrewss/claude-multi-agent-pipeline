---
name: ship
description: "Universal entry point for all code changes — from 1-file fixes to multi-story epics. Auto-classifies scope and routes internally (quickfix for <=5 files, full pipeline otherwise). Never skip /ship — it handles everything."
args:
  - name: args
    type: string
    description: "Title + feature list, PRD file path, plan file path, or epic ID. Optional flags: --quickfix, --quick, --argue."
---

# Ship Skill Invoked

User has requested: `/ship {{args}}`

## Flow control

**Continuous execution.** Steps 0 through 6 execute as one uninterrupted flow. Do not pause, narrate, summarize, or ask for confirmation between steps. The only legitimate stops are:
- An error that prevents the next step from running
- The sufficiency check in Step 0 (pure prose, no structure — explicit user gate)
- `No args` in Step 0 (nothing to work with)

Everything else flows. Step 1 output feeds Step 2 input feeds Step 3 input — no commentary in between.

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to determine the mode:

**Flags:**
- If `--quickfix` appears anywhere in args, set `quickfix_mode = true` and `quickfix_forced = true`. Strip from args. Force-override: bypasses auto-classification and always routes to quickfix (Step 0b).
- If `--quick` appears anywhere in args, set `skip_validate = true` and `skip_verify = true`. Strip from args. Skips plan validation (critique) and integrated review/verify. Per-story testing always runs (it's a run-stories concern, not a ship concern).
- If `--argue` appears anywhere in args, set `use_argue = true`. Strip from args. Uses adversarial debate instead of single-pass review for plan validation.

1. **Resume mode**: first token matches `epic-\d+` → set `epic_id` to that token.
2. **File mode**: a token ends with `.md` and the file exists → read it:
   - If file contains `## What changes` → **Execute mode** (existing plan file).
   - Otherwise → **PRD mode** (requirements doc). Read file contents, then check for a `## Summary` section:
     - If `## Summary` exists → **presearch briefing**. Extract `## Summary` content as `context` (not the full file). Extract numbered items from `## Features` > `### MVP` as `items`. Store the briefing path as `briefing_path` for use in later steps. Read and store the full file contents as `briefing_contents`.
     - If `## Summary` absent → existing behavior (full file as `context`).
3. **Inline mode**: everything else. Extract:
   - Quoted string or text before numbered items → `title`
   - `by YYYY-MM-DD` → `target_date`
   - Remaining numbered or comma-separated items → `items` list

   **Category detection (inline mode only):** After extracting items, scan the raw args text for category headers. A category header is a line matching either:
   - `**CategoryName:**` (bold markdown with colon)
   - `## CategoryName` (h2 markdown heading)

   If one or more category headers are found:
   1. Group subsequent numbered items under each header until the next header or end of input.
   2. Items appearing before the first category header become a category titled with the `umbrella_title` (the quoted string or text before the first header). This prevents item loss.
   3. Skip any category header that has zero items grouped under it. Log: `"Skipping empty category: <name>"`. If all categories are empty after skipping, fall through to the sufficiency check (which will catch "no structure").
   4. Build an `epics` list:
      ```json
      [
        {"title": "CategoryName1", "items": ["item1", "item2"]},
        {"title": "CategoryName2", "items": ["item3", "item4"]}
      ]
      ```
   5. Set `multi_epic_mode = true`. The top-level `title` (quoted string or text before the first header) becomes the `umbrella_title` -- used only for the final report header, not as an epic title.
   6. Set `items` to the flattened list of all items across all categories (for auto-classification's file count scan).

   If NO category headers are detected: leave `items`, `title` unchanged. Set `multi_epic_mode = false`. Existing single-epic behavior is unaffected.

   **Auto-classification (inline mode only):** After parsing, if `quickfix_mode` is not already set by the `--quickfix` flag, classify the task to determine routing. Scan the full description (title + items) for:

   - **File count**: Count tokens containing `/` or file extensions (`.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.md`, `.json`, `.yaml`, `.yml`, `.css`, `.html`, `.sh`, `.sql`). Store as `detected_file_count`.
   - **UI detection**: Check for UI keywords in the description or item titles: `component`, `screen`, `page`, `widget`, `view`, `layout`, `dashboard`, `form`, `panel`, `modal`, `dialog`, `sidebar`, `navbar`, `header`, `footer`, `card`, `redesign`, `UI`, `frontend`, `template`. This is language-agnostic — UI work in any framework (React, Flutter, Compose, SwiftUI, Vue, Angular, Rails ERB, Go templates, etc.) should be detected. Store as `has_ui_targets`.
   - **Schema keywords**: Check for any of: `Firestore`, `migration`, `schema`, `field rename`, `field delete`, `DB migration`, `API contract`, `type change`. (Note: `add field` alone is NOT a disqualifier — additive schema changes are quickfix-eligible.)
   - **AI tool keywords**: Check for any of: `toolDeclarations`, `toolExecutors`, `system prompt`.
   - **Protected file mentions**: If `<project-root>/.claude/protected-files.md` exists, read it and check whether any detected file paths appear in the protected list.

   Classification result:
   - If `detected_file_count` is 0 (no file tokens found): set `quickfix_eligible = false`. Log: `"Could not determine file targets from description — using full pipeline."`
   - If `has_ui_targets` is true: set `quickfix_eligible = false`. Log: `"UI write targets detected — routing to full pipeline (ui-coder agent required)."` UI work NEVER goes through quickfix because quickfix blocks `gemini_ui_code`.
   - If `detected_file_count` is 1-5 AND no schema keywords AND no AI tool keywords AND no protected file mentions AND NOT `has_ui_targets`: set `quickfix_eligible = true` and `quickfix_mode = true`. Log: `"Auto-routed to quickfix (<=N files, no schema/AI/protected/UI)."`
   - Otherwise: set `quickfix_eligible = false`. Proceed to sufficiency check below.

   **Component library check (inline mode only):** After classification, if `has_ui_targets` is true AND `quickfix_mode` is false:
   - Check if `<project-root>/components/ui/manifest.json` exists.
   - If missing: log `"No component library found. Consider running /gen-library <design spec> for faster UI stories."`
   - If found: read the manifest, count components. Log `"Component library found: N components. ui-coder agents will import from library."`
   - This is informational only — does not block the pipeline or prompt the user.

   **Sufficiency check (inline mode only):** After classification, check for actionable signals:
   - Specific technologies/frameworks mentioned? (e.g., "Stripe", "React", "Firebase")
   - Existing file paths referenced?
   - Numbered feature items (≥2)?
   - If ANY of these signals are present → pass through silently.
   - If NONE are present (pure prose, no structure), warn:
     ```
     This looks like a high-level idea. /presearch produces better results by
     researching APIs and constraints first. Continue anyway? (y/presearch)
     ```
   - User says "y" or similar → continue. User says "presearch" → invoke `/presearch` with the same args. This is a warning, not a gate.

4. **No args**: Ask the user: "Describe what to build (features or file path):" and stop.

```bash
bash ~/.claude/scripts/emit-event.sh "skill.ship.started" "claude" "ship" '{"mode":"'"$MODE"'"}'
```

---

## Step 0b: Quickfix dispatch

**Run when `quickfix_mode = true` (from `--quickfix` flag or auto-classification). On success, skip Steps 1-6 entirely.**

Print routing context:
- If `quickfix_forced = true`: `"Quickfix flag: skipping classification."`
- If `quickfix_eligible = true` (auto-classified): the auto-classification log line was already printed in Step 0.

Invoke:

```
Skill: quickfix, args: "<remaining args after flags stripped>"
```

/quickfix handles criteria validation, plan writing, branch creation, coder launch, and merge internally.

- **On /quickfix success**: print the result and STOP. Skip Steps 1-6.
- **On /quickfix error mentioning "criteria not met"**:
  - If `quickfix_forced = true`: warn user `"Quickfix criteria not met — falling back to full pipeline."`, set `quickfix_mode = false`, and continue to Step 1.
  - If `quickfix_eligible = true` (auto-classified): warn user `"Auto-classified as quickfix but criteria not met — falling back to full pipeline."`, set `quickfix_mode = false`, and continue to Step 1.
- **On /quickfix error for any other reason**: surface the error to the user and stop.

---

## Step 1: Plan stories

**Execute mode scope detection**: Before invoking /plan-stories, if execute mode was detected in Step 0, read the plan file and count write targets from the `## What changes` table. If ≤2 write targets: auto-set `skip_validate = true` and `skip_verify = true`.

Invoke /plan-stories based on the mode detected in Step 0:

- **Execute mode**: `Skill: plan-stories, args: "<plan file path>"`
- **Briefing mode**: `Skill: plan-stories, args: "presearch/<slug>.md"` (pass the briefing_path)
- **Inline mode (single epic)**: When `multi_epic_mode = false`:
  `Skill: plan-stories, args: "\"<title>\" 1. <item1> 2. <item2> ..."`

- **Inline mode (multi-epic)**: When `multi_epic_mode = true`:
  For each entry in `epics`:
    `Skill: plan-stories, args: "\"<epic.title>\" 1. <epic.items[0]> 2. <epic.items[1]> ..."`
  Run sequentially (each call creates its own epic and stories in the DB).
  After ALL calls complete, merge results: collect each call's `epic_id`, `dev_branch`, and `stories` list.

- **Resume mode**: `Skill: plan-stories, args: "epic-NNN"`

After /plan-stories completes:
- **Single epic**: read `.ship-manifest.json` to extract `epic_id`, `dev_branch`, and the story list.
- **Multi-epic**: each /plan-stories call writes its own `.ship-manifest.json` (overwriting the previous). Instead, after each call, capture the returned `epic_id`, `dev_branch`, and story list in memory before the next call. After all calls complete, build the merged manifest and write it to `.ship-manifest.json` once.

Multi-epic manifest structure:
```json
{
  "slug": "<derived from umbrella_title>",
  "scope": {
    "files": "<sum across all epics>",
    "stories": "<sum across all epics>",
    "complexity": "small | medium | large"
  },
  "route_hint": "standard",
  "multi_epic": true,
  "data": {
    "umbrella_title": "<umbrella_title>",
    "epics": [
      {
        "epic_id": "epic-NNN",
        "title": "CategoryName1",
        "dev_branch": "dev/<slug1>",
        "stories": [
          {"id": "story-NNN", "title": "...", "agent": "...", "detail_file": "..."}
        ]
      },
      {
        "epic_id": "epic-MMM",
        "title": "CategoryName2",
        "dev_branch": "dev/<slug2>",
        "stories": [...]
      }
    ]
  }
}
```

Single-epic manifests are unchanged -- `data.epic_id`, `data.dev_branch`, `data.stories` at top level, no `multi_epic` key.

On error: surface to the user and stop.

---

## Step 2: Draft plans

**Skip when**: execute mode (plan file already exists — /plan-stories just created DB entries, no new plans needed).

Build the args string:

- Start with: `.ship-manifest.json --skip-critique`
  (Always pass `--skip-critique` because /ship invokes /critique separately in Step 3.)
- If `briefing_path` was set in Step 0: append `--briefing <briefing_path>`

Invoke:

```
Skill: draft-plans, args: "<constructed args>"
```

On error: surface to the user and stop.

---

## Step 3: Critique plans

**Skip when**: `skip_validate = true` (--quick flag or execute mode with ≤2 write targets).

Collect plan file paths: read `.ship-manifest.json`, for each story extract the `plan_file` field (populated by /draft-plans or /plan-stories).

Invoke:

```
Skill: critique, args: "--plans <plan1.md> <plan2.md> ..."
```

Store critique output for the Step 6 report.

---

## Step 4: Environment preflight

**Skip when**: execute mode (existing plan file — user manages env).

Invoke:

```
Skill: env-preflight, args: ".ship-manifest.json"
```

/env-preflight handles silent skip internally if no deps detected.

---

## Step 5: Execute

Collect all story IDs from `.ship-manifest.json` (space-separated) and invoke:

```
Skill: run-stories, args: "<story-id-1> <story-id-2> ..."
```

---

## Step 5a: Report execution status

After `/run-stories` completes, print a summary:

**Single epic** (no `data.epics`):
```
Shipped: <epic title> (<epic_id>)
  story-NNN: <title> — <agent> — plan: plans/<name>.md — <DONE|BLOCKED>
  ...
```

**Multi-epic** (`data.epics` present):
```
Shipped: <umbrella_title>
  <epic.title> (<epic.epic_id>):
    story-NNN: <title> — <agent> — plan: plans/<name>.md — <DONE|BLOCKED>
    ...
  <epic.title> (<epic.epic_id>):
    story-NNN: <title> — <agent> — plan: plans/<name>.md — <DONE|BLOCKED>
    ...
```

If any stories are BLOCKED, list their reasons. Continue to Step 5b only if at least one story merged successfully (across ALL epics combined).

---

## Step 5b: Verify

**Skip when**: `skip_verify = true` (--quick flag or execute mode with ≤2 write targets) or zero stories merged.

Invoke:

```
Skill: verify, args: ".ship-manifest.json"
```

/verify handles integrated review, build, test, and acceptance criteria walk internally.

Store verify output for the Step 6 report.

---

## Step 5c: Enforcement gate

**This gate runs before the final report. It cannot be bypassed.**

Check whether required steps actually produced output:

1. **Critique gate**: If `skip_validate` is false:
   - Check if Step 3 stored critique output (any non-empty string).
   - If missing: **STOP. Do not generate the final report.** Print:
     > "BLOCKED: Critique (Step 3) was not run. This is required unless --quick flag is set. Run `/critique --plans <plan files>` now."
   - Run `/critique --plans <plan files>` immediately, then continue.

2. **Verify gate**: If `skip_verify` is false AND at least one story merged:
   - Check if Step 5b stored verify output (any non-empty string).
   - If missing: **STOP. Do not generate the final report.** Print:
     > "BLOCKED: Verify (Step 5b) was not run. This is required unless --quick flag is set. Run `/verify .ship-manifest.json` now."
   - Run `/verify .ship-manifest.json` immediately, then continue.

If both gates pass (or steps were legitimately skipped via flags), proceed to Step 6.

---

## Step 6: Final report

```bash
bash ~/.claude/scripts/emit-event.sh "skill.ship.completed" "claude" "ship" '{"epic_id":"'"$EPIC_ID"'"}'
```

Print final summary synthesized from child skill outputs:

**Single epic**:
```
Ship complete: <epic title> (<epic_id>)
  Stories: N merged, M blocked
  Critique: <from Step 3 output, or "skipped (--quick)">
  Review: <from /verify output, or "skipped (--quick)">
  Build: <from /verify output, or "skipped (--quick)">
  Tests: <from /verify output, or "skipped (--quick)">
  Acceptance: <from /verify output, or "skipped (--quick)">

Use /roadmap to check status.
```

**Multi-epic**:
```
Ship complete: <umbrella_title>
  Epics: K total
    <epic.title> (<epic.epic_id>): N merged, M blocked
    ...
  Stories: <total merged> merged, <total blocked> blocked (across all epics)
  Critique: <from Step 3 output, or "skipped (--quick)">
  Review: <from /verify output, or "skipped (--quick)">
  Build: <from /verify output, or "skipped (--quick)">
  Tests: <from /verify output, or "skipped (--quick)">
  Acceptance: <from /verify output, or "skipped (--quick)">

Use /roadmap to check status.
```

Critique, Review, Build, Tests, Acceptance lines remain unchanged -- they already aggregate across all stories regardless of epic grouping.
