---
name: ingest
description: >
  Load a roadmap file into epics.json, routing [code] stories through the epic-planner
  and creating manual checklist stories directly. Use when the user says "/ingest",
  "/ingest <path>", or "ingest roadmap".
---

# Ingest Skill

Read a structured roadmap markdown file (produced by `/roadmap` or hand-written) and
load it into `epics.json`. Code stories go through the epic-planner for decomposition;
manual steps become checklist stories directly.

## Step 1 — Resolve the roadmap file

1. Determine the project root: use the current working directory if it contains a
   `.claude/` folder; otherwise walk up until one is found.
2. Verify `<project-root>/.claude/epics.json` exists. If not, print:
   `No epics.json found at <project-root>/.claude/epics.json. Initialize the pipeline first.`
   and stop.
3. If `/ingest` was called **with a path argument**:
   - If the path is relative, resolve it against the project root.
   - Verify the file exists. If not, print `File not found: <path>` and stop.
   - Read the file.
4. If `/ingest` was called **with no args**:
   - Glob `<project-root>/.claude/roadmaps/*.md`.
   - If no files found: print `No roadmaps found in .claude/roadmaps/. Run /roadmap first.` and stop.
   - If one file found: use it automatically. Print `Using: <filename>`
   - If multiple files found: print `Available roadmaps:` followed by each path, then ask the user to pick via `AskUserQuestion`.

## Step 2 — Parse the roadmap

Extract structure from the roadmap file:

**Epics**: Lines matching `## Epic: <title>` → capture title.
**Epic descriptions**: The `> <description>` line immediately following an `## Epic:` line.
**Stories**: Lines under `### Stories` headings, in the format:
  - `- [code] <title> — <plan>` → automated story
  - `- [manual] <title>` → manual checklist step
  - `- <title> — <plan>` (untagged) → treat as `[code]`

Build a list of epics, each with:
```
{
  title: string,
  description: string,
  codeStories: [{title, plan}],
  manualSteps: [string]
}
```

If parsing produces zero epics, print `No epics found in roadmap. Check the file format.` and stop.

## Step 3 — Dedup check against epics.json

Read `<project-root>/.claude/epics.json`.

For each parsed epic title, check (case-insensitive) whether an epic with the same
title already exists in `epics.json` and is NOT in `closed` state.

If a match is found, print:
```
Warning: "<parsed title>" may duplicate epic-NNN "<existing title>" (state: <state>).
```
Then ask via `AskUserQuestion`:
```
How should this be handled?
  proceed — ingest anyway as a new epic
  skip     — skip this epic entirely
  abort    — stop ingestion
```

Collect responses for all duplicates before proceeding. If any response is `abort`, stop.

## Step 4 — Assign IDs

Read the current highest epic and story IDs from `epics.json` to determine the next
available numbers. Assign IDs for all new epics and manual stories now (before launching
planners). Do NOT assign IDs for code stories — the epic-planner will propose those.

Epic ID format: `epic-NNN` (zero-padded to 3 digits).
Story ID format: `story-NNN` (zero-padded to 3 digits).

## Step 5 — Process manual stories

For each epic that has `manualSteps`:

1. Determine the epic slug (lowercase title, hyphens for spaces, max 5 words).
2. Assign a story ID (from the pool allocated in Step 4).
3. Build the checklist file content:
   ```markdown
   # <Epic Title> — Manual Steps

   ## Steps
   - [ ] <manual step 1>
   - [ ] <manual step 2>
   ```
4. Write to `<project-root>/.claude/checklists/<epic-slug>.md`.
   Create the directory if it does not exist.
5. Record the story object (will be written to epics.json in Step 7):
   ```json
   {
     "id": "story-NNN",
     "epicId": "<assigned-epic-id>",
     "title": "Checklist: <epic-slug>",
     "state": "filling",
     "branch": null,
     "writeFiles": [".claude/checklists/<epic-slug>.md"],
     "needsTesting": false,
     "needsReview": false,
     "agent": "manual",
     "model": null
   }
   ```

## Step 6 — Launch epic-planners for code stories (background, parallel)

For each epic that has `codeStories` (and was not skipped in the dedup step):

Determine the model:
- Opus if the epic has >5 code stories, or if the title/description mentions "schema",
  "AI", "migration", or "database".
- Sonnet otherwise.

Launch an epic-planner agent **background** (`run_in_background: true`) with:

```
MODE: epic
Epic description: <epic title>

<epic description>

Stories to implement:
<numbered list of code story titles and one-line plans>

Absolute path to epics.json: <project-root>/.claude/epics.json
Absolute path to project root: <project-root>
Output path: $TMPDIR/epic-plan-<epic-slug>.md

Instructions:
- Research the codebase to determine write targets, agents, and models for each story.
- Each story item in the list above becomes one story in your output.
- Dedup against existing epics.json stories before finalizing.
- Follow ORCHESTRATION.md §19 output format exactly.
- Run the integration surface check per ORCHESTRATION.md §19.2.
```

Track each launched agent by epic slug. All planners run in parallel.

## Step 7 — Collect and validate planner output

Wait for all background planner agents to complete (check via TaskOutput).

For each planner output file at `$TMPDIR/epic-plan-<epic-slug>.md`:

1. Read the file.
2. Validate the STAGING_PAYLOAD JSON against ORCHESTRATION.md §6 schema:
   - Each story has: `id`, `epicId`, `title`, `state`, `branch`, `writeFiles`, `needsTesting`, `needsReview`
   - `writeFiles` is non-empty
   - `state` is `"filling"`
3. Collect validation errors. If any: print the error and mark this epic as failed.

If any epic failed validation, print:
```
Validation errors found. Failed epics:
  - <epic-slug>: <error>
Fix the roadmap or re-run. No changes written yet.
```
and stop (do NOT write partial results).

## Step 8 — Present consolidated summary

Print a summary of everything that will be written:

```
Ready to ingest:

Epic: <title> (epic-NNN)
  [code] story-NNN  <title>  <agent>  <model>
  [code] story-NNN  <title>  <agent>  <model>
  [manual] story-NNN  Checklist: <slug>  manual

Epic: <title> (epic-NNN)
  ...

Integration stories (auto-generated):
  story-NNN  Wire <feature> into <surface>  quick-fixer  haiku

Total: N epics, M code stories, K manual stories

Proceed? (approve / abort)
```

Ask via `AskUserQuestion`. If user says `abort`, stop without writing.

## Step 9 — Write to epics.json and create TaskCreate entries

On approval:

1. For each new epic, write via `update-epics.sh`:
   ```
   bash <project-root>/.claude/scripts/update-epics.sh '<project-root>' \
     '{"newEpic": {"id":"epic-NNN","title":"...","branch":null,"prNumber":null,"persistent":true}}'
   ```
   If `update-epics.sh` does not exist, write directly via node:
   ```bash
   node -e "
     const fs = require('fs');
     const p = '<project-root>/.claude/epics.json';
     const data = JSON.parse(fs.readFileSync(p,'utf8'));
     data.epics.push(<epic-object>);
     fs.writeFileSync(p, JSON.stringify(data,null,2));
   "
   ```

2. For each story (code + manual), write via `update-epics.sh`:
   ```
   bash <project-root>/.claude/scripts/update-epics.sh '<project-root>' \
     '{"newStory": <story-object>, "epicId": "epic-NNN"}'
   ```

3. Create `TaskCreate` entries for each story:
   - `title`: story title
   - `description`: `epic-NNN — <epic title>`

4. Print:
   ```
   Ingested <N> epics, <M> code stories, <K> manual steps.
   All stories in filling state. Use /run-story to start work.
   ```
   If checklist files were created:
   ```
   Checklist files written to .claude/checklists/:
     <epic-slug>.md  (<K> steps)
   Run /checklist <slug> to walk through manual steps.
   ```

## Notes

- All ingested stories land in `filling` state. No coders auto-launch.
- The `/run-story` skill controls when automated stories execute.
- The `/checklist` skill controls when manual steps are walked through.
- Checklist files are written whether or not the user runs `/checklist` immediately.
- Epic-planners may propose integration stories (per ORCHESTRATION.md §19.2). These appear
  in the consolidated summary under "Integration stories" and are staged like any other story.
- If a planner stalls (no output after 6 minutes), surface the error and ask the user
  whether to retry just that epic or abort the entire ingest.

## Roadmap file format (reference)

```markdown
# Authentication System

## Epic: Core Auth
> Implement email/password login and session management.

### Stories
- [code] Add login endpoint — implement POST /auth/login with bcrypt password check
- [code] Add session store — wire Redis-based session with 24h TTL
- [manual] Configure SMTP credentials in provider dashboard

## Epic: OAuth Integration
> Add Google and GitHub OAuth login flows.

### Stories
- [code] Add Google OAuth — implement OAuth2 flow with passport-google-oauth20
- [manual] Register OAuth app in Google Cloud Console
```
