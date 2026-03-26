# Context Essentials (post-compaction reinject)

## Critical rules — never violate
- All code changes go through /ship skill. Never edit code directly in main session.
- Never commit directly to main or dev. All work on named branches.
- Never push to remote without checking in first.
- Stage files by name. Never `git add -A`.
- Never create worktrees in the main session. Worktrees are for coder subagents only.

## Workflow
- /ship is the universal entry point for all code changes.
- When user says "ship it" → invoke /ship skill.
- Pipeline flows continuously — don't pause between steps for narration or confirmation.
- Skills invoke child skills. Don't bypass the skill chain.

## Communication
- Be direct and concise. No preamble, no trailing summaries.
- Take positions, don't ask permission to have opinions.
- Log corrections via `bash ~/.claude/scripts/log-correction.sh` BEFORE proceeding with corrected approach.

## Context recovery
- Check @.claude/rendered-prefs.md for behavioral preferences.
- Check ORCHESTRATION.md for pipeline rules.
- If working on stories, check session state via `pm_list_stories` or `pm_view`.
