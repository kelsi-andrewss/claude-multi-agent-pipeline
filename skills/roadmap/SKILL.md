---
name: roadmap
description: >
  Convert a research document into a structured roadmap markdown file with natural-language
  stories, ready for /ingest. Use when the user says "/roadmap", "/roadmap <path>",
  or "convert research to roadmap".
---

# Roadmap Skill

Convert a free-form research or requirements document into a structured roadmap
markdown file. The output is human-reviewable before ingestion into the pipeline.

## Step 1 — Resolve the research document

1. Determine the project root: use the current working directory if it contains a
   `.claude/` folder; otherwise walk up until one is found.
2. If `/roadmap` was called **with a path argument**:
   - If the path is relative, resolve it against the project root.
   - Verify the file exists. If not, print `File not found: <path>` and stop.
   - Read the file.
3. If `/roadmap` was called **with no args**:
   - Glob `<project-root>/.claude/research/*.md`.
   - If no files found: print `No research docs found in .claude/research/. Create one first.` and stop.
   - If one file found: use it automatically.
   - If multiple files found: print `Available research docs:` followed by each path, then ask the user to pick one via `AskUserQuestion`.

## Step 2 — Derive slug and output path

Derive a slug from the filename stem (lowercase, hyphens for spaces, strip special chars,
max 5 words). Example: `q3-auth-requirements.md` → `q3-auth-requirements`.

Output path: `<project-root>/.claude/roadmaps/<slug>.md`

## Step 3 — Analyze and structure inline

Read the research document carefully. Then do the following inline (no sub-agent):

1. Identify all discrete work items from the document.
2. Group related items into epics. Each epic is a coherent theme of work.
3. If grouping is ambiguous (e.g. "Should X and Y be one epic or two?"), ask via
   `AskUserQuestion`. Batch all questions together — ask at most 2-3 at once, never
   one at a time. Wait for answers before continuing.
4. For each epic, draft a one-sentence description of what it delivers.
5. For each epic, list the individual stories as top-level bullet points.
   - Sub-bullets under a story are detail/plan for that story — they are NOT separate stories.
   - For manual human actions (external dashboards, config steps, API key creation),
     include specific links and instructions in the sub-bullets.

## Step 4 — Write the roadmap file

1. Create `<project-root>/.claude/roadmaps/` if it does not exist.
2. Write the structured content to `<project-root>/.claude/roadmaps/<slug>.md`
   using the format below.

## Step 5 — Print completion message

```
Roadmap written to .claude/roadmaps/<slug>.md
Review and edit it, then run: /ingest .claude/roadmaps/<slug>.md
```

Also print a compact summary:
```
  <N> epics, <M> stories, <K> manual steps
```

## Notes

- The roadmap file is human-editable. Users should review and adjust before running `/ingest`.
- No `[code]`/`[manual]` tags in the output — ingest infers type from content.
- Sub-bullets are detail for the parent story, not separate stories.
- Manual steps should include direct links and specific instructions so a human can
  follow them without additional research.

## Roadmap file format (reference)

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
- Add GitHub OAuth
  - Implement OAuth2 flow with passport-github2
- Register OAuth app in Google Cloud Console
  - Go to https://console.cloud.google.com/apis/credentials
  - Create OAuth 2.0 Client ID, set redirect URI to /auth/google/callback
  - Add client ID and secret to .env as GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
- Register OAuth app in GitHub
  - Go to https://github.com/settings/developers
  - Create new OAuth App, set callback URL to /auth/github/callback
  - Add client ID and secret to .env as GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
```
