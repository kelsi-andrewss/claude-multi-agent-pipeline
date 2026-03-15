---
name: ship
description: "Thin orchestrator: routes user intent to child skills (/quickfix, /plan-stories, /draft-plans, /critique, /env-preflight, /run-stories, /verify) in sequence. Parses args, detects mode, and dispatches — never performs planning, critique, review, build, or test logic directly."
args:
  - name: args
    type: string
    description: "Title + feature list, PRD file path, plan file path, or epic ID. Optional flags: --quickfix, --quick, --argue."
---

# Ship Skill Invoked

User has requested: `/ship {{args}}`

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

   **Auto-classification (inline mode only):** After parsing, if `quickfix_mode` is not already set by the `--quickfix` flag, classify the task to determine routing. Scan the full description (title + items) for:

   - **File count**: Count tokens containing `/` or file extensions (`.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.md`, `.json`, `.yaml`, `.yml`, `.css`, `.html`, `.sh`, `.sql`). Store as `detected_file_count`.
   - **Schema keywords**: Check for any of: `Firestore`, `migration`, `schema`, `field rename`, `field delete`, `DB migration`, `API contract`, `type change`. (Note: `add field` alone is NOT a disqualifier — additive schema changes are quickfix-eligible.)
   - **AI tool keywords**: Check for any of: `toolDeclarations`, `toolExecutors`, `system prompt`.
   - **Protected file mentions**: If `<project-root>/.claude/protected-files.md` exists, read it and check whether any detected file paths appear in the protected list.

   Classification result:
   - If `detected_file_count` is 0 (no file tokens found): set `quickfix_eligible = false`. Log: `"Could not determine file targets from description — using full pipeline."`
   - If `detected_file_count` is 1-5 AND no schema keywords AND no AI tool keywords AND no protected file mentions: set `quickfix_eligible = true` and `quickfix_mode = true`. Log: `"Auto-routed to quickfix (<=N files, no schema/AI/protected)."`
   - Otherwise: set `quickfix_eligible = false`. Proceed to sufficiency check below.

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
- **Inline mode**: `Skill: plan-stories, args: "\"<title>\" 1. <item1> 2. <item2> ..."`
- **Resume mode**: `Skill: plan-stories, args: "epic-NNN"`

After /plan-stories completes, read `.ship-manifest.json` to extract `epic_id`, `dev_branch`, and the story list (IDs, titles, agents, detail_file paths).

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
```
Shipped: <epic title> (<epic_id>)
  story-NNN: <title> — <agent> — plan: plans/<name>.md — <DONE|BLOCKED>
  ...
```

If any stories are BLOCKED, list their reasons. Continue to Step 5b only if at least one story merged successfully.

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

## Step 6: Final report

Print final summary synthesized from child skill outputs:

```
Ship complete: <epic title> (<epic_id>)
  Stories: N merged, M blocked
  Review: <from /verify output, or "skipped">
  Integration: <from /verify output, or "skipped">
  Acceptance: <from /verify output, or "skipped">

Use /roadmap to check status.
```
