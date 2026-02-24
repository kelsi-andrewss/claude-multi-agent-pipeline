---
name: roadmap
description: >
  Convert a research document into a structured roadmap markdown file with tagged
  [code]/[manual] stories, ready for /ingest. Use when the user says "/roadmap",
  "/roadmap <path>", or "convert research to roadmap".
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

Output path: `$TMPDIR/roadmap-<slug>.md`
Final path: `<project-root>/.claude/roadmaps/<slug>.md`

## Step 3 — Launch epic-planner in planning mode (foreground)

Launch the epic-planner agent **foreground** (not background) with this prompt:

```
MODE: roadmap-conversion
Research document path: <absolute-path>
Research document content:
---
<full content of the research doc>
---

Project root: <absolute-path>
Output path: $TMPDIR/roadmap-<slug>.md

Task: Convert this research document into a structured roadmap markdown file.

Instructions:
1. Read the research document carefully. Identify discrete work items.
2. Group related items into epics. Each epic is a coherent theme of work.
3. For each epic, list individual stories tagged [code] or [manual]:
   - [code] — automated implementation work (will be handed to coder agents)
   - [manual] — human steps (deploy actions, external config, approvals, etc.)
4. Ask the user clarifying questions via AskUserQuestion if grouping is ambiguous
   (e.g. "Should X and Y be one epic or two?"). Batch questions — ask at most
   2-3 at once, never one at a time.
5. Write the output file at the specified path using the format below.
6. Do NOT write to epics.json. Do NOT run builds or tests.

Output format:
---
# <Project/Feature Title>

## Epic: <Epic Title>
> <one-sentence description of what this epic delivers>

### Stories
- [code] <Story title> — <one-line plan describing what the coder will do>
- [code] <Story title> — <one-line plan>
- [manual] <Human step description>

## Epic: <Another Epic Title>
> <description>

### Stories
- [code] <Story title> — <one-line plan>
- [manual] <Human step description>
---

Rules:
- Every story line must start with exactly `- [code]`, `- [manual]`, or `- ` (untagged, treated as [code])
- Epic titles must be unique
- Story titles must be concise (≤10 words)
- One-line plans must describe the implementation action, not the business outcome
- Manual steps describe a human action (e.g. "Configure OAuth app in provider dashboard")
- Keep epics to 3-8 stories each; split if larger
```

Wait for the planner to complete (foreground blocks).

## Step 4 — Read planner output and write roadmap file

1. Read `$TMPDIR/roadmap-<slug>.md`.
2. If the file is empty or missing, print `Planner did not produce output. Aborting.` and stop.
3. Create `<project-root>/.claude/roadmaps/` if it does not exist.
4. Write the content to `<project-root>/.claude/roadmaps/<slug>.md`.

## Step 5 — Print completion message

```
Roadmap written to .claude/roadmaps/<slug>.md
Review and edit it, then run: /ingest .claude/roadmaps/<slug>.md
```

Also print a compact summary of what was generated:
```
  <N> epics, <M> code stories, <K> manual steps
```

## Notes

- The roadmap file is human-editable. Users should review and adjust before running `/ingest`.
- Tags `[code]` and `[manual]` are case-sensitive — use lowercase.
- Untagged story lines (starting with `- ` but no tag) default to `[code]` at ingest time.
- The planner uses interactive mode — it may ask 1-3 grouping questions before writing output.
- If the user wants to skip the interactive step and accept defaults, they can tell the planner "use your judgment".

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
- [code] Add GitHub OAuth — implement OAuth2 flow with passport-github2
- [manual] Register OAuth app in Google Cloud Console
- [manual] Register OAuth app in GitHub developer settings
```
