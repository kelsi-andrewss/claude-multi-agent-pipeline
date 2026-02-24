---
name: roadmap-progress
description: >
  Show per-epic story-state progress derived from roadmap files and epics.json.
  Use when the user says "/roadmap-progress", "show roadmap progress", or
  "how many stories are done per epic". Read-only — does not modify any files
  or launch any agents.
---

# Roadmap Progress Skill

Read roadmap files from `.claude/roadmaps/` and cross-reference with
`epics.json` to show story-state tallies per epic, grouped by roadmap file.

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

- `filling` bucket: states `filling`, `queued`
- `in-progress` bucket: states `running`, `testing`, `reviewing`, `merging`, `blocked`
- `closed` bucket: state `closed`

Compute `total` = sum of all three buckets.

## Step 6 — Render output

For each roadmap file, print:

```
Roadmap: .claude/roadmaps/<filename>.md

  Epic: <title> (<epic-id>)
    filling:     N  [░░░░░░░░░░]
    in-progress: N  [██░░░░░░░░]
    closed:      N  [████░░░░░░]
    total:       N

  Epic: <uningested title> (uningested)
    Not yet loaded via /ingest.

Roadmap total: N epics  |  N filling  |  N in-progress  |  N closed
```

Progress bar rules:
- Width is always 10 characters.
- Filled characters: `floor(count / total * 10)`. Remainder: `░`.
- If `total` is 0, all characters are `░`.

ANSI color codes to apply (reset each with `\033[0m`):
- `filling` label and bar: `\033[2m` (dim)
- `in-progress` label and bar: `\033[32m` (green)
- `closed` label and bar: `\033[34m` (blue)

After printing all roadmaps, print a grand total line:
```
All roadmaps: N epics  |  N filling  |  N in-progress  |  N closed
```

If all matched epics across all roadmaps have zero stories outside the `closed`
bucket (i.e., filling + in-progress = 0 and closed > 0), also print:
```
\033[32mAll ingested epics are closed.\033[0m
```

## Notes

- Read-only. No file writes. No agent launches.
- Stories present in `epics.json` but not sourced from any roadmap file are
  not shown.
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
