---
name: hook-profile
description: Switch the active hook profile (minimal, standard, strict) or show the current one. Use when the user says "/hook-profile", "/hook-profile strict", "/hook-profile minimal", "/hook-profile standard", "change hook profile", or "show hook profile".
---

Manage the active hook profile. Profiles control which hooks run during the session.

**Levels:**
- `minimal` (1): load-session-context, cost-alert, session-learning-check
- `standard` (2): all of minimal + guard-protected-files, block-env-read, context-check, log-skill-invocation, track-skill-changes, warn-sync-heavy-bash
- `strict` (3): all of standard + guard-direct-edit, block-enter-worktree

**Arguments:** `$ARGUMENTS` — either a profile name (minimal/standard/strict) or empty to show current.

Steps:

1. If `$ARGUMENTS` is empty or "show" or "status":
   - Read `/tmp/claude-hook-profile` to get the current profile (default: standard)
   - Report the active profile and which hooks are enabled at that level

2. If `$ARGUMENTS` is a valid profile name (minimal, standard, strict):
   - Write the profile name to `/tmp/claude-hook-profile`:
     ```bash
     echo "<profile>" > /tmp/claude-hook-profile
     ```
   - Report: "Hook profile set to <profile>. Active hooks: <list>"

3. If `$ARGUMENTS` is not a recognized profile name:
   - Report: "Unknown profile '<value>'. Valid profiles: minimal, standard, strict"

Do not ask for confirmation. Execute immediately.
