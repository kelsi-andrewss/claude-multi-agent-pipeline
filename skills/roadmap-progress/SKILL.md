---
name: roadmap-progress
description: >
  Show per-epic story-state progress derived from roadmap files and epics.json.
  Use when the user says "/roadmap-progress", "show roadmap progress", or
  "how many stories are done per epic". Read-only — does not modify any files
  or launch any agents. Supports flags: --stalled, --shipped, epic-ID drill-in.
args:
  - name: flags
    type: string
    description: "Optional: epic ID to drill into, --stalled (only stalled epics), --shipped (include shipped)"
---

# Roadmap Progress Skill

Read roadmap files from `.claude/roadmaps/` and cross-reference with
`epics.json` to show story-state tallies per epic, grouped by roadmap file.

## Flag modes

- `/roadmap-progress` — summary + interactive menu
- `/roadmap-progress epic-005` — drill into one epic
- `/roadmap-progress --stalled` — only epics with draft/blocked stories
- `/roadmap-progress --shipped` — include shipped epics

## Step 1 — Resolve project root

Use the current working directory if it contains a `.claude/` folder; otherwise
walk up until one is found.

## Step 2 — Locate roadmap files

Glob `<project-root>/.claude/roadmaps/*.md`.

If no files are found, print:
```
No roadmaps found in .claude/roadmaps/. Run /roadmap then /ingest first.
```
and stop.

## Step 3 — Parse roadmap files

For each roadmap file:

1. Scan for epic headings. Two formats are supported:
   - Old format: lines matching `## Epic: <title>` → capture the title after `Epic: `.
   - New format: lines matching `## <title>` where the title does NOT start with `Epic:` → capture as-is.
2. For each epic heading, check the immediately following non-empty line:
   - Old format: if it starts with `> `, capture it as the epic description (trim the leading `> `).
   - New format: if it is plain prose (not a bullet or heading), capture it as the epic description.
3. Build a map: `filename → [epicTitle, ...]` preserving order of appearance.

## Step 4 — Read epics.json

Read `<project-root>/.claude/epics.json`.

For each extracted epic title, find a matching entry in `epics.json` using
case-insensitive exact title match against `epic.title`.

Record titles that have no match as **uningested**.

## Step 5 — Tally story states

For each matched epic, iterate its `stories` array and classify each story's
`state` into one of three buckets:

- `draft` bucket: states `draft`, `ready`
- `active` bucket: states `in-progress`, `in-review`, `approved`, `blocked`
- `done` bucket: states `done`, `shipped`

Compute `total` = sum of all three buckets.

## Step 6 — Render output

### If drilling into a specific epic (`/roadmap-progress epic-005`)

Show detailed view:

```
Epic: <title> (<epic-id>)  state: <epic-state>
Source: .claude/roadmaps/<filename>.md

Stories:
  story-NNN  [in-progress]  <title>  architect  sonnet  (3/5 tasks)
  story-NNN  [done]         <title>  quick-fixer  haiku
  story-NNN  [in-progress]  Checklist: deploy  manual  (2/4 steps)
  story-NNN  [blocked]      <title>  — blocked since <date if known>

Actions: /run-story <id> | /defer <id> | /rescope <id>
```

For code stories with tasks: show task progress "(<done>/<total> tasks)".
For manual stories: read checklist file, count `[x]` vs `[ ]`, show "(<done>/<total> steps)".

### Default summary view

For each roadmap file, print:

```
Roadmap: .claude/roadmaps/<filename>.md

  Epic: <title> (<epic-id>)
    draft:   N  [░░░░░░░░░░]
    active:  N  [██░░░░░░░░]
    done:    N  [████░░░░░░]
    total:   N

  Epic: <uningested title> (uningested)
    Not yet loaded via /ingest.

Roadmap total: N epics  |  N draft  |  N active  |  N done
```

If `--stalled`: only show epics that have stories in `draft` or `blocked` state.

If `--shipped`: include epics with state `shipped` (normally hidden).

Progress bar rules:
- Width is always 10 characters.
- Filled characters: `floor(count / total * 10)`. Remainder: `░`.
- If `total` is 0, all characters are `░`.

ANSI color codes to apply (reset each with `\033[0m`):
- `draft` label and bar: `\033[2m` (dim)
- `active` label and bar: `\033[32m` (green)
- `done` label and bar: `\033[34m` (blue)

After printing all roadmaps, print a grand total line:
```
All roadmaps: N epics  |  N draft  |  N active  |  N done
```

If all matched epics across all roadmaps have zero stories outside the `done`
bucket (i.e., draft + active = 0 and done > 0), also print:
```
\033[32mAll ingested epics are done.\033[0m
```

### Interactive menu (after summary table)

After the summary, print:
```
[1] Drill into an epic
[2] Show stalled stories
[3] Show backlog
[4] Done
```

Ask via `AskUserQuestion`. On selection:
- **1**: Ask which epic ID, then re-render as drill-in view.
- **2**: Re-render with `--stalled` filter.
- **3**: Show backlog stories from backlog epic.
- **4**: Stop.

## Notes

- Read-only. No file writes. No agent launches.
- Stories present in `epics.json` but not sourced from any roadmap file are
  not shown (except in drill-in mode which reads directly from epics.json).
- Uningested = title appears in a roadmap file but has no matching entry in
  `epics.json`.
- Do NOT read ORCHESTRATION.md. Do NOT modify epics.json or any roadmap file.

## Roadmap file format (reference)

New natural-language format (preferred):

```markdown
# Authentication System

## Core Auth
Implement email/password login and session management.

- Add login endpoint
  - Implement POST /auth/login with bcrypt password check
  - Return signed JWT with 24h expiry
- Add session store
  - Wire Redis-based session with 24h TTL
- Configure SMTP credentials
  - Go to https://resend.com/api-keys
  - Create a key with "Sending access" scope
  - Add to .env as RESEND_API_KEY

## OAuth Integration
Add Google and GitHub OAuth login flows.

- Add Google OAuth
  - Implement OAuth2 flow with passport-google-oauth20
- Register OAuth app in Google Cloud Console
  - Go to https://console.cloud.google.com/apis/credentials
  - Create OAuth 2.0 Client ID, set redirect URI to /auth/google/callback
  - Add client ID and secret to .env as GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
```

Old format (still supported for backwards compatibility):

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
